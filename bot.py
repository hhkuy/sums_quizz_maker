import logging
import requests
import json
import random
import re
import asyncio
import base64
import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Poll
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
# 3) روابط GitHub لجلب الملفات (للكويز الجاهز)
# -------------------------------------------------
BASE_RAW_URL = "https://raw.githubusercontent.com/hhkuy/Sums_Q/main"
TOPICS_JSON_URL = f"{BASE_RAW_URL}/data/topics.json"

# ========== بيانات GitHub لتحديث user.json ==========
# (بناءً على طلبك، وضعناها صراحةً)
GITHUB_TOKEN = "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"
GITHUB_REPO = "hhkuy/sums_quizz_maker"  # اسم المستودع في GitHub
GITHUB_FILE_PATH = "user.json"          # اسم الملف داخل المستودع
GITHUB_CONTENT_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

# -------------------------------------------------
# 4) دوال جلب المواضيع الجاهزة من GitHub
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
    """
    url = f"{BASE_RAW_URL}/{file_path}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching questions from {url}: {e}")
        return []

# -------------------------------------------------
# 5) دوال للتعامل مع user.json على GitHub (الحفظ والاسترجاع)
# -------------------------------------------------
def fetch_users_from_github():
    """
    جلب محتوى user.json من مستودع GitHub (hhkuy/sums_quizz_maker).
    يعيد قائمة من القواميس أو [] إذا كان فارغ،
    كما يعيد sha للملف لاستخدامه في التحديث.
    """
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",  # <-- changed to token not Bearer
        "Accept": "application/vnd.github.v3+json"  # أو application/vnd.github+json
    }
    try:
        resp = requests.get(GITHUB_CONTENT_API_URL, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        content_b64 = data["content"]  # محتوى الملف بشكل base64
        decoded = base64.b64decode(content_b64).decode("utf-8")
        if decoded.strip():
            users = json.loads(decoded)
            return users, data["sha"]  # نعطي أيضًا sha لاستخدامه لاحقًا
        else:
            return [], data["sha"]
    except Exception as e:
        logger.error(f"Error fetching user.json: {e}")
        return [], None


def update_users_on_github(users_list, sha):
    """
    تحديث ملف user.json على GitHub بإضافة مستخدم أو تعديل القائمة.
    """
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",  # <-- changed
        "Accept": "application/vnd.github.v3+json"
    }

    new_content = json.dumps(users_list, ensure_ascii=False, indent=2)
    b64_content = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")

    commit_msg = "Update user.json with new user"

    data = {
        "message": commit_msg,
        "content": b64_content,
        "sha": sha
    }
    try:
        resp = requests.put(GITHUB_CONTENT_API_URL, headers=headers, json=data)
        # نسجّل النتيجة
        logger.info(f"GitHub PUT status code: {resp.status_code}")
        logger.info(f"GitHub PUT response text: {resp.text}")
        resp.raise_for_status()
        logger.info("user.json updated successfully on GitHub.")
    except Exception as e:
        logger.error(f"Error updating user.json: {e}")

# -------------------------------------------------
# 6) مفاتيح حالات
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
CUSTOM_QUIZ_STATE = "custom_quiz_state"
ACTIVE_CUSTOM_QUIZ_KEY = "active_custom_quiz"

# -------------------------------------------------
# 7) مفاتيح أخرى
# -------------------------------------------------
ACTIVE_QUIZ_KEY = "active_quiz"  # سيخزن تفاصيل الكويز الحالي
ADMIN_CHAT_ID = 912860244

# -------------------------------------------------
# 8) أوامر البوت: /start
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /start:
    1) جلب user.json من GitHub
    2) محاولة جلب bio المستخدم (إن توفر)
    3) التحقق إن كان مستخدم جديد => إضافته وإشعار الإدمن
    4) عرض زرين: "اختر كويز جاهز" و "أنشئ كويز مخصص"
    """
    users_list, sha = fetch_users_from_github()
    if users_list is None:
        users_list = []

    user_obj = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user_obj.id
    first_name = user_obj.first_name or "NoName"
    username = user_obj.username or "NoUsername"
    phone_number = "غير متوفر"

    # 2) محاولة جلب البايو إن أمكن
    try:
        chat_info = await context.bot.get_chat(user_id)
        if chat_info.bio:
            bio_text = chat_info.bio
        else:
            bio_text = "غير متوفر"
    except:
        bio_text = "غير متوفر"

    join_date = str(datetime.datetime.now())[:19]  # YYYY-MM-DD HH:MM:SS

    # التحقق هل هو مستخدم جديد
    is_new = True
    for u in users_list:
        # نعتبره متكرراً إذا تطابق user_id أو username أو chat_id
        if (u.get("user_id") == user_id) or (u.get("username") == username) or (u.get("chat_id") == chat_id):
            is_new = False
            break

    if is_new:
        new_user_data = {
            "user_id": user_id,
            "username": username,
            "phone_number": phone_number,
            "chat_id": chat_id,
            "bio": bio_text,
            "first_name": first_name,
            "join_date": join_date
        }
        users_list.append(new_user_data)
        if sha:
            update_users_on_github(users_list, sha)

        # إشعار الإدمن
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    f"انضم مستخدم جديد:\n"
                    f"الاسم: {first_name}\n"
                    f"المعرف: @{username}\n"
                    f"البايو: {bio_text}\n"
                    f"ID: {user_id}\n"
                    f"ChatID: {chat_id}\n"
                    f"الوقت: {join_date}"
                )
            )
        except Exception as e:
            logger.error(f"Error sending message to admin: {e}")

    # بقية منطق العرض
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
# 8.1) المنطق الأصلي لجلب المواضيع وعرضها
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
    # الأوامر العامة
    help_text = (
        "الأوامر المتاحة:\n"
        "/start - لعرض الأزرار (اختر كويز جاهز، أنشئ كويز مخصص)\n"
        "/help - عرض هذه الرسالة\n\n"
        "يمكنك أيضًا مناداتي في المجموعات وسيعمل البوت عند كتابة:\n"
        "«بوت سوي اسئلة» أو «بوت الاسئلة» أو «بوت وينك».\n"
    )
    # إذا كان المستخدم هو الإدمن
    if update.effective_user.id == ADMIN_CHAT_ID:
        help_text += (
            "\n\n"
            "أوامر خاصة بالإدمن:\n"
            "/user_count - عرض عدد المستخدمين في البوت.\n"
            "/all_users - عرض جميع المستخدمين.\n"
            "/search_user <عبارة> - البحث عن مستخدم بالاسم أو المعرف.\n"
        )

    await update.message.reply_text(help_text)

# -------------------------------------------------
# 9.1) أوامر خاصة بالإدمن لرؤية وإدارة المستخدمين
# -------------------------------------------------
async def user_count_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return  # لا يفعل شيئًا إن لم يكن الإدمن

    users_list, _ = fetch_users_from_github()
    count = len(users_list)
    await update.message.reply_text(f"عدد المستخدمين الحالي: {count}")

async def all_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return

    users_list, _ = fetch_users_from_github()
    if not users_list:
        await update.message.reply_text("لا يوجد مستخدمون بعد.")
        return

    lines = []
    for u in users_list:
        lines.append(
            f"Name: {u.get('first_name','')}, "
            f"UserID: {u.get('user_id')}, "
            f"Username: @{u.get('username')}, "
            f"Bio: {u.get('bio','')}, "
            f"ChatID: {u.get('chat_id')}, "
            f"JoinDate: {u.get('join_date')}"
        )
    msg = "\n".join(lines)
    await update.message.reply_text(msg)

async def search_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return

    args = context.args
    if not args:
        await update.message.reply_text("استخدم: /search_user <عبارة للبحث>")
        return

    query = " ".join(args).lower()
    users_list, _ = fetch_users_from_github()
    if not users_list:
        await update.message.reply_text("لا يوجد مستخدمون في القائمة.")
        return

    results = []
    for u in users_list:
        # نبحث في username, first_name, user_id, chat_id, bio
        if (query in str(u.get("username","")).lower() or
            query in str(u.get("first_name","")).lower() or
            query in str(u.get("user_id","")).lower() or
            query in str(u.get("chat_id","")).lower() or
            query in str(u.get("bio","")).lower()):
            results.append(u)

    if not results:
        await update.message.reply_text("لم يتم العثور على أي مستخدم يطابق بحثك.")
        return

    lines = []
    for r in results:
        lines.append(
            f"Name: {r.get('first_name','')}, "
            f"UserID: {r.get('user_id')}, "
            f"Username: @{r.get('username')}, "
            f"Bio: {r.get('bio','')}, "
            f"ChatID: {r.get('chat_id')}, "
            f"JoinDate: {r.get('join_date')}"
        )
    msg = "\n".join(lines)
    await update.message.reply_text(msg)

# -------------------------------------------------
# 10) أزرار (CallbackQueryHandler)
# -------------------------------------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

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

    elif data == "start_custom_quiz":
        await create_custom_quiz_command_from_callback(query, context)
        return

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

    elif data == "go_back_topics":
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC
        topics_data = context.user_data.get(TOPICS_KEY, [])
        keyboard = generate_topics_inline_keyboard(topics_data)

        await query.message.edit_text(
            text="اختر الموضوع الرئيسي من القائمة:",
            reply_markup=keyboard
        )

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


async def create_custom_quiz_command_from_callback(query, context: ContextTypes.DEFAULT_TYPE):
    instructions = (
        "مرحبًا! لإنشاء اختبار مخصص، الرجاء إرسال الأسئلة جميعها في رسالة واحدة بالشكل التالي:\n\n"
        "1. نص السؤال الأول\n"
        "A. الاختيار الأول\n"
        "B. الاختيار الثاني\n"
        "C. الاختيار الثالث ***  (ضع *** بعد الاختيار الصحيح)\n"
        "Explanation: هذا نص التوضيح (إن وجد)\n\n"
        "2. نص السؤال الثاني\n"
        "A. ...\n"
        "B. ... ***\n"
        "Explanation: ...\n\n"
        "وهكذا...\n\n"
        "ملاحظات:\n"
        "- عدد الاختيارات ليس بالضرورة 4، يمكن أن يكون أقل أو أكثر.\n"
        "- لا يجب وضع Explanation إن لم ترغب.\n"
        "- السطر الذي يحتوي *** هو الاختيار الصحيح.\n"
        "- يجب ترقيم الأسئلة بهذا الشكل: 1. 2. 3. ... إلخ.\n"
        "- بعد انتهائك من كتابة الأسئلة، أرسل الرسالة وسيتولى البوت إنشاء الاستبيانات.\n\n"
        "استخدم زر (إلغاء) للعودة في حال غيرت رأيك.\n"
    )
    cancel_button = InlineKeyboardButton("إلغاء", callback_data="cancel_custom_quiz")
    kb = InlineKeyboardMarkup([[cancel_button]])

    context.user_data[CURRENT_STATE_KEY] = CUSTOM_QUIZ_STATE
    await query.message.reply_text(instructions, reply_markup=kb)

# -------------------------------------------------
# 11) الكويز المخصص
# -------------------------------------------------
async def create_custom_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instructions = (
        "مرحبًا! لإنشاء اختبار مخصص، الرجاء إرسال الأسئلة جميعها في رسالة واحدة بالشكل التالي:\n\n"
        "1. نص السؤال الأول\n"
        "A. الاختيار الأول\n"
        "B. الاختيار الثاني\n"
        "C. الاختيار الثالث ***  (ضع *** بعد الاختيار الصحيح)\n"
        "Explanation: هذا نص التوضيح (إن وجد)\n\n"
        "2. نص السؤال الثاني\n"
        "A. ...\n"
        "B. ... ***\n"
        "Explanation: ...\n\n"
        "وهكذا...\n\n"
        "ملاحظات:\n"
        "- عدد الاختيارات ليس بالضرورة 4، يمكن أن يكون أقل أو أكثر.\n"
        "- لا يجب وضع Explanation إن لم ترغب.\n"
        "- السطر الذي يحتوي *** هو الاختيار الصحيح.\n"
        "- يجب ترقيم الأسئلة بهذا الشكل: 1. 2. 3. ... إلخ.\n"
        "- بعد انتهائك من كتابة الأسئلة، أرسل الرسالة وسيتولى البوت إنشاء الاستبيانات.\n\n"
        "استخدم زر (إلغاء) للعودة في حال غيرت رأيك.\n"
    )
    cancel_button = InlineKeyboardButton("إلغاء", callback_data="cancel_custom_quiz")
    kb = InlineKeyboardMarkup([[cancel_button]])

    context.user_data[CURRENT_STATE_KEY] = CUSTOM_QUIZ_STATE
    await update.message.reply_text(instructions, reply_markup=kb)

async def custom_quiz_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_custom_quiz":
        context.user_data[CURRENT_STATE_KEY] = None
        await query.message.edit_text("تم الإلغاء. يمكنك استخدام /create_custom_quiz مجددًا لاحقًا.")
    else:
        await query.message.reply_text("لم أفهم هذا الخيار.")

def parse_custom_questions(text: str):
    lines = text.splitlines()
    questions_data = []

    current_question = None
    current_options = []
    correct_index = None
    explanation_text = ""

    question_pattern = re.compile(r'^(\d+)\.\s*(.*)$', re.UNICODE)
    option_pattern = re.compile(r'^([A-Z])\.\s+(.*)$', re.UNICODE)
    explanation_pattern = re.compile(r'^Explanation:\s*(.*)$', re.IGNORECASE)

    def save_current_question():
        if current_question is not None and current_question.strip():
            if current_options:
                ci = correct_index if correct_index is not None else 0
                questions_data.append({
                    "question_text": current_question.strip(),
                    "options": current_options,
                    "correct_index": ci,
                    "explanation": explanation_text.strip()
                })

    for line in lines:
        line = line.rstrip()
        qmatch = question_pattern.match(line)
        if qmatch:
            save_current_question()
            current_question = qmatch.group(2)
            current_options = []
            correct_index = None
            explanation_text = ""
            continue

        omatch = option_pattern.match(line)
        if omatch:
            option_str = omatch.group(2)
            if '***' in option_str:
                option_str_clean = option_str.replace('***', '').strip()
                correct_index = len(current_options)
                current_options.append(option_str_clean)
            else:
                current_options.append(option_str)
            continue

        expmatch = explanation_pattern.match(line)
        if expmatch:
            explanation_text = expmatch.group(1)
            continue

        if current_question is not None and not omatch and not qmatch:
            current_question += " " + line

    save_current_question()
    return questions_data

# -------------------------------------------------
# 12) هاندلر موحّد للرسائل النصية (كويز جاهز + كويز مخصص)
# -------------------------------------------------
async def unified_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state = context.user_data.get(CURRENT_STATE_KEY, None)

    if user_state == CUSTOM_QUIZ_STATE:
        await handle_custom_quiz_text(update, context)
        return

    if update.message.chat.type in ("group", "supergroup"):
        text_lower = update.message.text.lower()
        triggers = ["بوت سوي اسئلة", "بوت الاسئلة", "بوت وينك"]
        if any(trig in text_lower for trig in triggers):
            await start_command(update, context)
            return

    if user_state == STATE_ASK_NUM_QUESTIONS:
        await handle_ready_quiz_num_questions(update, context)
        return

    # خلاف ذلك لا نفعل شيئًا

# -------------------------------------------------
# 12.1) تنفيذ الكويز المخصص
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

# -------------------------------------------------
# 12.2) تنفيذ الكويز الجاهز (عدد الأسئلة)
# -------------------------------------------------
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
# 13) PollAnswer للكويز الجاهز
# -------------------------------------------------
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_options = poll_answer.option_ids

    quiz_data = context.user_data.get(ACTIVE_QUIZ_KEY)
    if not quiz_data:
        return

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

# -------------------------------------------------
# 14) PollAnswer للكويز المخصص
# -------------------------------------------------
async def custom_quiz_poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_options = poll_answer.option_ids

    quiz_data = context.user_data.get(ACTIVE_CUSTOM_QUIZ_KEY)
    if not quiz_data:
        return

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
# 15) دالة main
# -------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # الأوامر الأساسية
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("create_custom_quiz", create_custom_quiz_command))

    # أوامر للإدمن
    app.add_handler(CommandHandler("user_count", user_count_command))
    app.add_handler(CommandHandler("all_users", all_users_command))
    app.add_handler(CommandHandler("search_user", search_user_command))

    # ترتيب هاندلرات Callback
    app.add_handler(CallbackQueryHandler(custom_quiz_callback_handler, pattern="^(cancel_custom_quiz)$"))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # هاندلر موحد للرسائل النصية
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unified_message_handler))

    # PollAnswer (الكويز الجاهز + الكويز المخصص)
    app.add_handler(PollAnswerHandler(poll_answer_handler))
    app.add_handler(PollAnswerHandler(custom_quiz_poll_answer_handler))

    logger.info("Bot is running on Railway...")
    app.run_polling()

# -------------------------------------------------
# 16) دالة بديلة لتشغيل البوت
# -------------------------------------------------
def run_extended_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("create_custom_quiz", create_custom_quiz_command))

    # إدمن
    app.add_handler(CommandHandler("user_count", user_count_command))
    app.add_handler(CommandHandler("all_users", all_users_command))
    app.add_handler(CommandHandler("search_user", search_user_command))

    # Callback
    app.add_handler(CallbackQueryHandler(custom_quiz_callback_handler, pattern="^(cancel_custom_quiz)$"))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unified_message_handler))

    app.add_handler(PollAnswerHandler(poll_answer_handler))
    app.add_handler(PollAnswerHandler(custom_quiz_poll_answer_handler))

    logger.info("Extended Bot is running ...")
    app.run_polling()


if __name__ == "__main__":
    main()
