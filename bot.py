import logging
import requests
import json
import random
import re
import asyncio
import base64
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Poll,
    Chat
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    PollAnswerHandler,
    MessageHandler,
    filters
)

# -------------------------------------------------
# 1) تهيئة نظام اللوج
# -------------------------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------------------------------------
# 2) توكن البوت - تم وضعه مباشرةً
# -------------------------------------------------
BOT_TOKEN = "7633072361:AAHnzREYTKKRFiTiq7HDZBalnwnmgivY8_I"

# -------------------------------------------------
# 2.1) بيانات GitHub للتعامل مع user.json
# -------------------------------------------------
GITHUB_TOKEN = "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"
GITHUB_REPO_OWNER = "hhkuy"
GITHUB_REPO_NAME = "sums_quizz_maker"
FILE_PATH_IN_REPO = "user.json"

# سنستخدم هذا الرابط لجلب الملف (للقراءة فقط)
RAW_FILE_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/main/{FILE_PATH_IN_REPO}"

# -------------------------------------------------
# 3) روابط GitHub لجلب الملفات (الكويز الجاهز)
# -------------------------------------------------
BASE_RAW_URL = "https://raw.githubusercontent.com/hhkuy/Sums_Q/main"
TOPICS_JSON_URL = f"{BASE_RAW_URL}/data/topics.json"

# -------------------------------------------------
# 4) دوال جلب البيانات من GitHub (الكويز الجاهز)
# -------------------------------------------------
def fetch_topics():
    """جلب ملف الـ topics.json من مستودع GitHub على شكل list[dict]."""
    try:
        response = requests.get(TOPICS_JSON_URL)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching topics: {e}")
        return []


def fetch_questions(file_path: str):
    """
    جلب ملف الأسئلة من مستودع GitHub بالاعتماد على المسار (file_path) الخاص بالموضوع الفرعي.
    مثال: data/anatomy_of_limbs_lower_limbs.json
    """
    url = f"{BASE_RAW_URL}/{file_path}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()  # قائمة من القواميس (الأسئلة)
    except Exception as e:
        logger.error(f"Error fetching questions from {url}: {e}")
        return []

# -------------------------------------------------
# 5) مفاتيح لحفظ الحالة في context.user_data
# -------------------------------------------------
TOPICS_KEY = "topics"
CUR_TOPIC_IDX_KEY = "current_topic_index"
CUR_SUBTOPIC_IDX_KEY = "current_subtopic_index"
NUM_QUESTIONS_KEY = "num_questions"
CURRENT_STATE_KEY = "current_state"
QUESTIONS_KEY = "questions_list"

STATE_SELECT_TOPIC = "select_topic"
STATE_SELECT_SUBTOPIC = "select_subtopic"
STATE_ASK_NUM_QUESTIONS = "ask_num_questions"
STATE_SENDING_QUESTIONS = "sending_questions"

# -------------------------------------------------
# 6) مفاتيح إضافية لحفظ بيانات الكويز/النتائج
# -------------------------------------------------
ACTIVE_QUIZ_KEY = "active_quiz"  # سيخزن تفاصيل الكويز الحالي (poll_ids وغيرها)

# -------------------------------------------------
# 6.1) إعدادات خاصة لتخزين بيانات المستخدمين
# -------------------------------------------------
ADMIN_CHAT_ID = 912860244  # هذا هو الأدمن الوحيد
ACTIVE_CUSTOM_QUIZ_KEY = "active_custom_quiz"
CUSTOM_QUIZ_STATE = "custom_quiz_state"

# -------------------------------------------------
# دوال للتعامل مع user.json في GitHub
# -------------------------------------------------
def get_github_file_sha_and_content():
    """
    يحضر الـSHA والمحتوى الحالي لملف user.json من مستودع GitHub
    لاستخدامه عند التعديل (PUT). يعيد tuple: (sha, content_as_dict)
    """
    api_url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{FILE_PATH_IN_REPO}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        resp = requests.get(api_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        sha = data["sha"]
        file_content = data["content"]
        decoded_content = base64.b64decode(file_content).decode("utf-8")
        # نفترض أن الملف يحوي JSON
        content_dict = json.loads(decoded_content)

        return sha, content_dict
    except Exception as e:
        logger.error(f"Error fetching user.json from GitHub: {e}")
        return None, {}

def update_github_user_json(new_content_dict, old_sha):
    """
    يحدّث ملف user.json بالمحتوى الجديد عبر استدعاء PUT على API GitHub
    """
    api_url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{FILE_PATH_IN_REPO}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # حوّل الدكت إلى نص JSON
    new_json_str = json.dumps(new_content_dict, ensure_ascii=False, indent=2)
    # شفّر Base64
    encoded_content = base64.b64encode(new_json_str.encode("utf-8")).decode("utf-8")

    commit_msg = "Update user.json automatically from telegram bot"

    put_data = {
        "message": commit_msg,
        "content": encoded_content,
        "sha": old_sha
    }

    try:
        resp = requests.put(api_url, headers=headers, data=json.dumps(put_data))
        resp.raise_for_status()
        logger.info("user.json updated successfully on GitHub.")
    except Exception as e:
        logger.error(f"Error updating user.json on GitHub: {e}")


def add_or_check_user(user_id, chat_id, username, phone_number, bio, first_name, last_name):
    """
    يتحقق هل هذا المستخدم موجود في user.json. إن لم يكن, يُضاف.
    يعيد (is_new_user, total_users_count).
    """
    sha, content = get_github_file_sha_and_content()
    if sha is None or not isinstance(content, dict):
        # ملف user.json فارغ أو فشلنا بجلبه، ننشئ دكت جديد
        content = {"users": [], "total": 0}
        sha = None

    # قد لا يكون لديه "users" و "total"
    if "users" not in content:
        content["users"] = []
    if "total" not in content:
        content["total"] = 0

    users_list = content["users"]

    # نتحقق إن كان موجود:
    # المعايير الممكنة: user_id, chat_id, username
    # سنفترض user_id كافٍ للتمييز + username + chat_id
    found = False
    for u in users_list:
        if u.get("id") == user_id or u.get("chat_id") == chat_id or (username and u.get("username") == username):
            found = True
            break

    if found:
        return False, content["total"]  # مستخدم قديم

    # مستخدم جديد:
    new_user_data = {
        "id": user_id,
        "chat_id": chat_id,
        "username": username,
        "phone": phone_number,
        "bio": bio,
        "first_name": first_name,
        "last_name": last_name,
        "join_date": datetime.now().isoformat()
    }
    users_list.append(new_user_data)
    content["total"] += 1

    # حدّث الملف في GitHub
    old_sha = sha if sha else ""  # إذا لم يكن هناك sha سابق
    update_github_user_json(content, old_sha)

    return True, content["total"]

# -------------------------------------------------
# 7) دوال لإنشاء الأزرار (InlineKeyboard)
# -------------------------------------------------
def generate_topics_inline_keyboard(topics_data):
    """
    إنشاء إنلاين كيبورد لقائمة المواضيع الرئيسية.
    """
    keyboard = []
    for i, topic in enumerate(topics_data):
        btn = InlineKeyboardButton(
            text=topic["topicName"],
            callback_data=f"topic_{i}"
        )
        keyboard.append([btn])
    return InlineKeyboardMarkup(keyboard)


def generate_subtopics_inline_keyboard(topic, topic_index):
    """
    إنشاء إنلاين كيبورد لقائمة المواضيع الفرعية + زر الرجوع.
    """
    keyboard = []
    subtopics = topic.get("subTopics", [])
    for j, sub in enumerate(subtopics):
        btn = InlineKeyboardButton(
            text=sub["name"],
            callback_data=f"subtopic_{topic_index}_{j}"
        )
        keyboard.append([btn])

    # زر الرجوع لقائمة المواضيع
    back_btn = InlineKeyboardButton("« رجوع للمواضيع", callback_data="go_back_topics")
    keyboard.append([back_btn])

    return InlineKeyboardMarkup(keyboard)

# -------------------------------------------------
# 8) أوامر البوت: /start
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /start:
    - نقوم بحفظ/التحقق من المستخدم في user.json
    - نعرض زرين: 1) اختر كويز جاهز. 2) أنشئ كويز مخصص.
    """
    # 1) نجلب معلومات المستخدم
    user = update.message.from_user
    chat_id = update.message.chat_id

    # سنحاول جلب bio (نبذة) إن أمكن
    try:
        chat_info = await context.bot.get_chat(user.id)
        user_bio = chat_info.bio if hasattr(chat_info, "bio") else None
    except:
        user_bio = None

    # لا يمكننا جلب رقم الهاتف من التيليجرام مباشرة إلا في سياقات محددة
    # سنضعه None أو لو كان لديك طريقة أخرى لجلبه
    phone_number = None

    is_new_user, total_users = add_or_check_user(
        user_id=user.id,
        chat_id=chat_id,
        username=user.username,
        phone_number=phone_number,
        bio=user_bio,
        first_name=user.first_name,
        last_name=user.last_name
    )

    # إذا كان مستخدم جديد، نرسل للـ admin إشعارًا
    if is_new_user:
        text_for_admin = (
            f"انضم مستخدم جديد للبوت!\n"
            f"Name: {user.first_name or ''} {user.last_name or ''}\n"
            f"Username: @{user.username}\n"
            f"UserID: {user.id}\n"
            f"ChatID: {chat_id}\n"
            f"Total Users Now: {total_users}\n"
        )
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text_for_admin)

    keyboard = [
        [InlineKeyboardButton("اختر كويز جاهز", callback_data="start_ready_quiz")],
        [InlineKeyboardButton("أنشئ كويز مخصص", callback_data="start_custom_quiz")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    welcome_message = (
        "هلا بيك نورت بوت حصرة ال dog 😵‍💫🚬\n\n"
        "تم صنعه من قِبل : [@h_h_k9](https://t.me/h_h_k9) 🙏🏻\n\n"
        "البوت تكدر تستعمله لصنع كوز جاهز ( يستخدم اسئلة فاينلات ) ✅ او صنع كويز مخصص ( ترسل الاسئلة للبوت وفق التعليمات و هو يتكفل بيهن و يصنعلك الاسئلة ) ⬆️👍🏻\n\n"
        "البوت تكدر تستعمله دايركت او كروبات ( ترفعه ادمن مع صلاحيات ارسال الرسائل ) اذا حبيتوا تسون كوز جماعي 🔥\n\n"
        "ونطلب منكم الدعاء وشكراً ✨\n\n"
        "هسة أختار احد الاختيارين و كول يا الله و صلِ على محمد و أل محمد :"
    )

    await update.message.reply_text(
        welcome_message,
        parse_mode="Markdown",
        reply_markup=markup
    )

# -------------------------------------------------
# 8.1) المنطق الأصلي لجلب المواضيع وعرضها (كان في start_command سابقًا)
# -------------------------------------------------
async def start_command_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topics_data = fetch_topics()
    context.user_data[TOPICS_KEY] = topics_data

    if not topics_data:
        await update.message.reply_text(
            "حدث خطأ في جلب المواضيع من GitHub! تأكد من صلاحية الرابط."
        )
        return

    context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC
    keyboard = generate_topics_inline_keyboard(topics_data)

    await update.message.reply_text(
        text="اختر الموضوع الرئيسي من القائمة:",
        reply_markup=keyboard
    )

# -------------------------------------------------
# 9) أوامر البوت: /help
# -------------------------------------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "الأوامر المتاحة:\n"
        "/start - لعرض الأزرار (اختر كويز جاهز، أنشئ كويز مخصص)\n"
        "/help - عرض هذه الرسالة\n\n"
        "يمكنك أيضًا مناداتي في المجموعات وسيعمل البوت عند كتابة:\n"
        "«بوت سوي اسئلة» أو «بوت الاسئلة» أو «بوت وينك».\n"
    )
    # إضافة أمر سري للأدمن لرؤية المستخدمين
    if update.message.chat_id == ADMIN_CHAT_ID:
        help_text += "\n/addons - أوامر إدارية لرؤية المستخدمين والبحث."

    await update.message.reply_text(help_text)

# -------------------------------------------------
# أوامر إدارية خاصة بالأدمن فقط
# -------------------------------------------------
async def admin_addons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # يتحقق إن كان الأدمن
    if update.message.chat_id != ADMIN_CHAT_ID:
        return  # نتجاهله
    text = "ماذا تريد أن تفعل؟\n" \
           "/show_users - يعرض عدد المستخدمين وقائمة مختصرة\n" \
           "(يمكنك إضافة أوامر أخرى للبحث وغيرها)"
    await update.message.reply_text(text)

async def show_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != ADMIN_CHAT_ID:
        return
    sha, content = get_github_file_sha_and_content()
    if not content or "users" not in content:
        await update.message.reply_text("لا يوجد مستخدمون بعد.")
        return
    total = content.get("total", len(content["users"]))
    msg = f"عدد المستخدمين حاليًا: {total}\n\n"
    # نعرض قائمة مختصرة
    for idx, u in enumerate(content["users"], start=1):
        fname = u.get("first_name", "")
        lname = u.get("last_name", "")
        uname = u.get("username", "")
        msg += f"{idx}. {fname} {lname} (@{uname})\n"
    await update.message.reply_text(msg)

# -------------------------------------------------
# 10) هاندلر للأزرار (CallbackQueryHandler)
# -------------------------------------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # زر "اختر كويز جاهز" من /start
    if data == "start_ready_quiz":
        topics_data = fetch_topics()
        context.user_data[TOPICS_KEY] = topics_data
        if not topics_data:
            await query.message.reply_text(
                "حدث خطأ في جلب المواضيع من GitHub! تأكد من صلاحية الرابط."
            )
            return
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC
        keyboard = generate_topics_inline_keyboard(topics_data)
        await query.message.reply_text(
            text="اختر الموضوع الرئيسي من القائمة:",
            reply_markup=keyboard
        )
        return

    # زر "أنشئ كويز مخصص" من /start
    elif data == "start_custom_quiz":
        await create_custom_quiz_command_from_callback(query, context)
        return

    # 1) اختيار موضوع رئيسي
    if data.startswith("topic_"):
        _, idx_str = data.split("_")
        topic_index = int(idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = topic_index
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_SUBTOPIC

        topics_data = context.user_data.get(TOPICS_KEY, [])
        if topic_index < 0 or topic_index >= len(topics_data):
            await query.message.reply_text("خيار غير صحيح.")
            return

        chosen_topic = topics_data[topic_index]
        subtopics_keyboard = generate_subtopics_inline_keyboard(chosen_topic, topic_index)
        msg_text = (
            f"اختر الموضوع الفرعي لـ: *{chosen_topic['topicName']}*\n\n"
            f"{chosen_topic.get('description', '')}"
        )

        await query.message.edit_text(
            text=msg_text,
            parse_mode="Markdown",
            reply_markup=subtopics_keyboard
        )

    # 2) زر الرجوع لقائمة المواضيع
    elif data == "go_back_topics":
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC
        topics_data = context.user_data.get(TOPICS_KEY, [])
        keyboard = generate_topics_inline_keyboard(topics_data)

        await query.message.edit_text(
            text="اختر الموضوع الرئيسي من القائمة:",
            reply_markup=keyboard
        )

    # 3) اختيار موضوع فرعي
    elif data.startswith("subtopic_"):
        _, t_idx_str, s_idx_str = data.split("_")
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CUR_SUBTOPIC_IDX_KEY] = s_idx
        context.user_data[CURRENT_STATE_KEY] = STATE_ASK_NUM_QUESTIONS

        back_btn = InlineKeyboardButton(
            "« رجوع للمواضيع الفرعية",
            callback_data=f"go_back_subtopics_{t_idx}"
        )
        kb = InlineKeyboardMarkup([[back_btn]])

        await query.message.edit_text(
            text="أدخل عدد الأسئلة المطلوبة (أرسل رقمًا فقط):",
            reply_markup=kb
        )

    # 4) زر الرجوع لقائمة المواضيع الفرعية
    elif data.startswith("go_back_subtopics_"):
        _, t_idx_str = data.split("_subtopics_")
        t_idx = int(t_idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_SUBTOPIC

        topics_data = context.user_data.get(TOPICS_KEY, [])
        if 0 <= t_idx < len(topics_data):
            chosen_topic = topics_data[t_idx]
            subtopics_keyboard = generate_subtopics_inline_keyboard(chosen_topic, t_idx)
            msg_text = (
                f"اختر الموضوع الفرعي لـ: *{chosen_topic['topicName']}*\n\n"
                f"{chosen_topic.get('description', '')}"
            )

            await query.message.edit_text(
                text=msg_text,
                parse_mode="Markdown",
                reply_markup=subtopics_keyboard
            )
        else:
            await query.message.edit_text("خيار غير صحيح.")

    else:
        await query.message.reply_text("لم أفهم هذا الخيار.")

# -------------------------------------------------
# 12) هاندلر موحد للرسائل النصية
# -------------------------------------------------
async def unified_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state = context.user_data.get(CURRENT_STATE_KEY, None)

    # 1) لو المستخدم في وضع الكويز المخصص
    if user_state == CUSTOM_QUIZ_STATE:
        await handle_custom_quiz_text(update, context)
        return

    # 2) لو الرسالة في مجموعة وتحوي تريغرات => نفذ /start
    if update.message.chat.type in ("group", "supergroup"):
        text_lower = update.message.text.lower()
        triggers = ["بوت سوي اسئلة", "بوت الاسئلة", "بوت وينك"]
        if any(trig in text_lower for trig in triggers):
            await start_command(update, context)
            return

    # 3) لو المستخدم في مرحلة طلب عدد الأسئلة (الكويز الجاهز)
    if user_state == STATE_ASK_NUM_QUESTIONS:
        await handle_ready_quiz_num_questions(update, context)
        return

    # 4) بخلاف ذلك:
    pass

# -------------------------------------------------
# 13) دوال معالجات الكويز المخصص والجاهز
# -------------------------------------------------
async def handle_custom_quiz_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    questions_data = parse_custom_questions(text)

    if not questions_data:
        await update.message.reply_text("لم يتم العثور على أسئلة بالصيغة المطلوبة. تأكد من التنسيق.")
        return

    poll_ids = []
    poll_correct_answers = {}
    owner_id = update.message.from_user.id
    chat_id = update.message.chat_id

    for item in questions_data:
        question_text = item["question_text"]
        options = item["options"]
        correct_index = item["correct_index"]
        explanation = item["explanation"]

        sent_msg = await context.bot.send_poll(
            chat_id=chat_id,
            question=question_text,
            options=options,
            type=Poll.QUIZ,
            correct_option_id=correct_index,
            explanation=explanation,
            is_anonymous=False
        )
        if sent_msg.poll is not None:
            pid = sent_msg.poll.id
            poll_ids.append(pid)
            poll_correct_answers[pid] = correct_index

        await asyncio.sleep(1)

    context.user_data[ACTIVE_CUSTOM_QUIZ_KEY] = {
        "owner_id": owner_id,
        "chat_id": chat_id,
        "poll_ids": poll_ids,
        "poll_correct_answers": poll_correct_answers,
        "total": len(questions_data),
        "correct_count": 0,
        "wrong_count": 0,
        "answered_count": 0
    }

    context.user_data[CURRENT_STATE_KEY] = None
    await update.message.reply_text(f"تم إنشاء {len(questions_data)} سؤال(أسئلة) بنجاح!")


async def handle_ready_quiz_num_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("من فضلك أدخل رقمًا صحيحًا.")
        return

    num_q = int(text)
    if num_q <= 0:
        await update.message.reply_text("العدد يجب أن يكون أكبر من صفر.")
        return

    context.user_data[NUM_QUESTIONS_KEY] = num_q
    context.user_data[CURRENT_STATE_KEY] = STATE_SENDING_QUESTIONS

    topics_data = context.user_data.get(TOPICS_KEY, [])
    t_idx = context.user_data.get(CUR_TOPIC_IDX_KEY, 0)
    s_idx = context.user_data.get(CUR_SUBTOPIC_IDX_KEY, 0)

    if t_idx < 0 or t_idx >= len(topics_data):
        await update.message.reply_text("خطأ في اختيار الموضوع.")
        return

    subtopics = topics_data[t_idx].get("subTopics", [])
    if s_idx < 0 or s_idx >= len(subtopics):
        await update.message.reply_text("خطأ في اختيار الموضوع الفرعي.")
        return

    file_path = subtopics[s_idx]["file"]
    questions = fetch_questions(file_path)
    if not questions:
        await update.message.reply_text("لم أتمكن من جلب أسئلة لهذا الموضوع الفرعي.")
        return

    if num_q > len(questions):
        await update.message.reply_text(
            f"الأسئلة غير كافية. العدد المتاح هو: {len(questions)}"
        )
        return

    random.shuffle(questions)
    selected_questions = questions[:num_q]

    await update.message.reply_text(
        f"سيتم إرسال {num_q} سؤال(أسئلة) على شكل استفتاء (Quiz). بالتوفيق!"
    )

    poll_ids = []
    poll_correct_answers = {}
    owner_id = update.message.from_user.id
    chat_id = update.message.chat_id

    for idx, q in enumerate(selected_questions, start=1):
        raw_question = q.get("question", "سؤال بدون نص!")
        clean_question = re.sub(r"<.*?>", "", raw_question).strip()
        clean_question = re.sub(r"(Question\s*\d+)", r"\1 -", clean_question)

        options = q.get("options", [])
        correct_id = q.get("answer", 0)
        explanation = q.get("explanation", "")

        sent_msg = await context.bot.send_poll(
            chat_id=chat_id,
            question=clean_question,
            options=options,
            type=Poll.QUIZ,
            correct_option_id=correct_id,
            explanation=explanation,
            is_anonymous=False
        )

        if sent_msg.poll is not None:
            pid = sent_msg.poll.id
            poll_ids.append(pid)
            poll_correct_answers[pid] = correct_id

        await asyncio.sleep(1)

    context.user_data[ACTIVE_QUIZ_KEY] = {
        "owner_id": owner_id,
        "chat_id": chat_id,
        "poll_ids": poll_ids,
        "poll_correct_answers": poll_correct_answers,
        "total": num_q,
        "correct_count": 0,
        "wrong_count": 0,
        "answered_count": 0
    }

    context.user_data[CURRENT_STATE_KEY] = None

# -------------------------------------------------
# 14) PollAnswerHandlers للكويز الجاهز والمخصص
# -------------------------------------------------
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_options = poll_answer.option_ids

    quiz_data = context.user_data.get(ACTIVE_QUIZ_KEY)
    if not quiz_data:
        return  # لا يوجد كويز جاهز فعّال

    if poll_id not in quiz_data["poll_ids"]:
        return

    if user_id != quiz_data["owner_id"]:
        return

    if len(selected_options) == 1:
        chosen_index = selected_options[0]
        correct_option_id = quiz_data["poll_correct_answers"][poll_id]

        quiz_data["answered_count"] += 1
        if chosen_index == correct_option_id:
            quiz_data["correct_count"] += 1
        else:
            quiz_data["wrong_count"] += 1

        if quiz_data["answered_count"] == quiz_data["total"]:
            correct = quiz_data["correct_count"]
            wrong = quiz_data["wrong_count"]
            total = quiz_data["total"]
            user_mention = f'<a href="tg://user?id={user_id}">{poll_answer.user.first_name}</a>'
            msg = (
                f"تم الانتهاء من الإجابة على {total} سؤال بواسطة {user_mention}.\n"
                f"الإجابات الصحيحة: {correct}\n"
                f"الإجابات الخاطئة: {wrong}\n"
                f"النتيجة النهائية: {correct} / {total}\n"
            )
            await context.bot.send_message(
                chat_id=quiz_data["chat_id"],
                text=msg,
                parse_mode="HTML"
            )
            context.user_data[ACTIVE_QUIZ_KEY] = None


async def custom_quiz_poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_options = poll_answer.option_ids

    quiz_data = context.user_data.get(ACTIVE_CUSTOM_QUIZ_KEY)
    if not quiz_data:
        return  # لا يوجد كويز مخصص فعّال

    if poll_id not in quiz_data["poll_ids"]:
        return

    if user_id != quiz_data["owner_id"]:
        return

    if len(selected_options) == 1:
        chosen_index = selected_options[0]
        correct_option_id = quiz_data["poll_correct_answers"][poll_id]

        quiz_data["answered_count"] += 1
        if chosen_index == correct_option_id:
            quiz_data["correct_count"] += 1
        else:
            quiz_data["wrong_count"] += 1

        if quiz_data["answered_count"] == quiz_data["total"]:
            correct = quiz_data["correct_count"]
            wrong = quiz_data["wrong_count"]
            total = quiz_data["total"]
            user_mention = f'<a href="tg://user?id={user_id}">{poll_answer.user.first_name}</a>'
            msg = (
                f"تم الانتهاء من الإجابة على {total} سؤال (الاختبار المخصص) بواسطة {user_mention}.\n"
                f"الإجابات الصحيحة: {correct}\n"
                f"الإجابات الخاطئة: {wrong}\n"
                f"النتيجة النهائية: {correct} / {total}\n"
            )
            await context.bot.send_message(
                chat_id=quiz_data["chat_id"],
                text=msg,
                parse_mode="HTML"
            )
            context.user_data[ACTIVE_CUSTOM_QUIZ_KEY] = None

# -------------------------------------------------
# 15) دالة main لتشغيل البوت
# -------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # الأوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))

    # أوامر إدارية للأدمن
    app.add_handler(CommandHandler("addons", admin_addons_command))
    app.add_handler(CommandHandler("show_users", show_users_command))

    app.add_handler(CommandHandler("create_custom_quiz", create_custom_quiz_command))

    # قدّم هاندلر إلغاء الكويز المخصص قبل الهاندلر العام
    app.add_handler(CallbackQueryHandler(custom_quiz_callback_handler, pattern="^(cancel_custom_quiz)$"))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # هاندلر موحد للرسائل النصية
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unified_message_handler))

    # PollAnswerHandlers
    app.add_handler(PollAnswerHandler(poll_answer_handler))
    app.add_handler(PollAnswerHandler(custom_quiz_poll_answer_handler))

    logger.info("Bot is running on Railway...")
    app.run_polling()

# -------------------------------------------------
# 16) دالة بديلة لتشغيل البوت بالميزات نفسها
# -------------------------------------------------
def run_extended_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))

    # أوامر إدارية للأدمن
    app.add_handler(CommandHandler("addons", admin_addons_command))
    app.add_handler(CommandHandler("show_users", show_users_command))

    app.add_handler(CommandHandler("create_custom_quiz", create_custom_quiz_command))

    app.add_handler(CallbackQueryHandler(custom_quiz_callback_handler, pattern="^(cancel_custom_quiz)$"))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unified_message_handler))

    app.add_handler(PollAnswerHandler(poll_answer_handler))
    app.add_handler(PollAnswerHandler(custom_quiz_poll_answer_handler))

    logger.info("Extended Bot is running ...")
    app.run_polling()


if __name__ == "__main__":
    main()
