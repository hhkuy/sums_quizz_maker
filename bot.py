import logging
import requests
import json
import random
import re
import asyncio
from datetime import datetime

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
# بيانات GitHub للتخزين
# -------------------------------------------------
GITHUB_TOKEN = "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"
REPO_OWNER = "hhkuy"
REPO_NAME = "sums_quizz_maker"
USER_FILE_PATH = "user.json"  # المسار داخل المستودع
ADMIN_CHAT_ID = 912860244     # الأدمن الوحيد الذي تصله تنبيهات الانضمام ويمتلك الميزات الإضافية

# -------------------------------------------------
# 3) روابط GitHub لجلب الملفات
# -------------------------------------------------
BASE_RAW_URL = "https://raw.githubusercontent.com/hhkuy/Sums_Q/main"
TOPICS_JSON_URL = f"{BASE_RAW_URL}/data/topics.json"

# -------------------------------------------------
# 4) دوال جلب البيانات من GitHub (للكويز الجاهز)
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
# == GitHub user.json التخزين في ==
# -------------------------------------------------

def get_user_json_info():
    """
    إحضار محتوى user.json من المستودع + إرجاع (data, sha)
    data: محتوى JSON على شكل dict أو list
    sha: معرف الملف لرفعه لاحقًا
    """
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{USER_FILE_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        jdata = resp.json()
        content_str = jdata["content"]
        import base64
        decoded = base64.b64decode(content_str).decode("utf-8")
        data = json.loads(decoded)
        sha = jdata["sha"]
        return data, sha
    except Exception as e:
        logger.error(f"Error fetching user.json from GitHub: {e}")
        # لو فشل إحضار الملف نعيد قيمة ابتدائية فارغة
        return [], None


def push_user_json(data, sha):
    """
    رفع التعديلات إلى GitHub مع تحديث الملف user.json
    data: dict أو list تمثل بيانات المستخدمين
    sha: التعرّف الخاص بالملف السابق (لمنع التعارض)
    """
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{USER_FILE_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    updated_content = json.dumps(data, ensure_ascii=False, indent=2)
    import base64
    encoded = base64.b64encode(updated_content.encode("utf-8")).decode("utf-8")

    commit_msg = "Update user.json from bot"

    payload = {
        "message": commit_msg,
        "content": encoded,
        "sha": sha,
        "branch": "main"
    }

    try:
        resp = requests.put(url, headers=headers, json=payload)
        resp.raise_for_status()
        logger.info("Successfully updated user.json on GitHub.")
    except Exception as e:
        logger.error(f"Error updating user.json on GitHub: {e}")


async def add_or_update_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    إضافة المستخدم أو تحديث بياناته في user.json على GitHub.
    - إذا كان مستخدم جديد ⇒ إرسال تنبيه للأدمن.
    - إذا موجود ⇒ لا إرسال شيء.
    """
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    # جلب معلومات الدردشة لتعبئة bio (لو أمكن)
    try:
        chat_info = await context.bot.get_chat(user_id)
    except Exception:
        chat_info = None

    user_bio = ""
    if chat_info and hasattr(chat_info, "bio") and chat_info.bio:
        user_bio = chat_info.bio
    phone_number = ""  # تيليجرام عادة لا يعطي الرقم للمستخدم دون مشاركة

    user_name = update.message.from_user.first_name or ""
    user_username = update.message.from_user.username or ""
    # في بعض الأحيان last_name
    if update.message.from_user.last_name:
        user_name += f" {update.message.from_user.last_name}"
    user_data = {
        "user_id": user_id,
        "chat_id": chat_id,
        "name": user_name,
        "username": user_username,
        "phone": phone_number,
        "bio": user_bio,
        "date_joined": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # 1) قراءة الملف الحالي
    current_data, sha = get_user_json_info()
    if not isinstance(current_data, list):
        current_data = []

    # 2) تحقق إن كان المستخدم موجودًا سابقًا
    # نعتبر "user_id" هو المفتاح
    found_existing = False
    for item in current_data:
        if (item.get("user_id") == user_id) or (item.get("chat_id") == chat_id) or (item.get("username") and item["username"] == user_username and user_username != ""):
            found_existing = True
            break

    # إذا موجود ⇒ لا نضيفه
    if found_existing:
        return  # لا نرسل رسالة للأدمن

    # إذا جديد ⇒ إضافته + إخطار الأدمن
    current_data.append(user_data)
    # تحديث الملف
    push_user_json(current_data, sha)

    # إرسال رسالة للأدمن
    # "تم انضمام شخص جديد" مع معلوماته
    text_msg = (
        f"انضم مستخدم جديد إلى البوت:\n\n"
        f"Name: {user_name}\n"
        f"Username: @{user_username if user_username else 'No username'}\n"
        f"UserID: {user_id}\n"
        f"ChatID: {chat_id}\n"
        f"Bio: {user_bio}\n"
        f"تاريخ الدخول: {user_data['date_joined']}\n\n"
        "تمت إضافته إلى user.json ✅"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text_msg)
    except Exception as e:
        logger.error(f"Failed to send admin message: {e}")


async def admin_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    أوامر إدارية خاصة بالأدمن فقط (ADMIN_CHAT_ID).
    مثل: /total_users, /list_users, /search_user
    """
    user_id = update.message.from_user.id
    if user_id != ADMIN_CHAT_ID:
        return  # تجاهل أي شخص آخر

    text = update.message.text.strip()
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd == "/total_users":
        # جلب user.json وعدّهم
        data, _ = get_user_json_info()
        if isinstance(data, list):
            count = len(data)
            await update.message.reply_text(f"عدد المستخدمين الكلي: {count}")
        else:
            await update.message.reply_text("لا توجد بيانات مستخدمين بعد.")

    elif cmd == "/list_users":
        data, _ = get_user_json_info()
        if isinstance(data, list) and data:
            msg_list = []
            for idx, u in enumerate(data, start=1):
                msg_list.append(f"{idx}) {u.get('name','??')} (ID: {u.get('user_id','')})")
            await update.message.reply_text("\n".join(msg_list))
        else:
            await update.message.reply_text("لا توجد بيانات مستخدمين بعد.")

    elif cmd.startswith("/search_user"):
        # /search_user Ahmed
        if len(parts) < 2:
            await update.message.reply_text("اكتب /search_user <عبارة البحث>")
            return
        query = parts[1].lower()
        data, _ = get_user_json_info()
        if isinstance(data, list) and data:
            results = []
            for u in data:
                # نبحث في الاسم أو اليوزرنيم أو البايو...
                combined_str = f"{u.get('name','')} {u.get('username','')} {u.get('bio','')}".lower()
                if query in combined_str:
                    results.append(u)
            if results:
                lines = []
                for r in results:
                    lines.append(f"- {r.get('name','?')} (ID:{r.get('user_id','')}, user:{r.get('username','')})")
                resp = "نتائج البحث:\n" + "\n".join(lines)
                await update.message.reply_text(resp)
            else:
                await update.message.reply_text("لم يتم العثور على مستخدمين.")
        else:
            await update.message.reply_text("لا توجد بيانات مستخدمين.")
    elif cmd == "/all_users_info":
        # يرسل جميع المعلومات التفصيلية
        data, _ = get_user_json_info()
        if isinstance(data, list) and data:
            # ربما يكون الرد طويلًا جدًا. يمكن تقسيمه
            big_lines = []
            for idx, u in enumerate(data, start=1):
                big_lines.append(
                    f"{idx}) Name: {u.get('name','')}\n"
                    f"   Username: {u.get('username','')}\n"
                    f"   UserID: {u.get('user_id','')}\n"
                    f"   ChatID: {u.get('chat_id','')}\n"
                    f"   Phone: {u.get('phone','')}\n"
                    f"   Bio: {u.get('bio','')}\n"
                    f"   Joined: {u.get('date_joined','')}\n"
                )
            full_text = "\n".join(big_lines)
            # لو طويل جدًا يتجزأ
            if len(full_text) < 4000:
                await update.message.reply_text(full_text)
            else:
                # تقسيمه
                chunks = [full_text[i:i+4000] for i in range(0, len(full_text), 4000)]
                for ch in chunks:
                    await update.message.reply_text(ch)
        else:
            await update.message.reply_text("لا توجد بيانات مستخدمين.")
    else:
        await update.message.reply_text("أمر إداري غير معروف. استخدم /total_users أو /list_users أو /search_user أو /all_users_info.")

# -------------------------------------------------
# 8) أوامر البوت: /start
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /start:
    - نعرض زرين: 1) اختر كويز جاهز. 2) أنشئ كويز مخصص.
    - أيضًا نقوم بتسجيل المستخدم في user.json إن لم يكن موجودًا.
    """
    # إضافة تسجيل / تحديث المستخدم
    await add_or_update_user(update, context)

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
    user_id = update.message.from_user.id
    help_text = (
        "الأوامر المتاحة:\n"
        "/start - لعرض الأزرار (اختر كويز جاهز، أنشئ كويز مخصص)\n"
        "/help - عرض هذه الرسالة\n\n"
        "يمكنك أيضًا مناداتي في المجموعات وسيعمل البوت عند كتابة:\n"
        "«بوت سوي اسئلة» أو «بوت الاسئلة» أو «بوت وينك».\n"
    )
    if user_id == ADMIN_CHAT_ID:
        # إضافة أوامر إدارية
        help_text += (
            "\n\nالأوامر الإدارية (خاصة بالأدمن):\n"
            "/total_users - عرض عدد المستخدمين\n"
            "/list_users - عرض أسماء المستخدمين\n"
            "/search_user <نص> - البحث عن مستخدمين\n"
            "/all_users_info - معلومات مفصلة عن الجميع\n"
        )
    await update.message.reply_text(help_text)

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
# 12) هاندلر (إلغاء) الكويز المخصص
# -------------------------------------------------
async def custom_quiz_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_custom_quiz":
        context.user_data[CURRENT_STATE_KEY] = None
        await query.message.edit_text("تم الإلغاء. يمكنك استخدام /create_custom_quiz مجددًا لاحقًا.")
    else:
        await query.message.reply_text("خيار غير مفهوم.")


# -------------------------------------------------
# 13) كود الكويز المخصص: parse_custom_questions + unified_message_handler
# -------------------------------------------------
def parse_custom_questions(text: str):
    """
    تحليل نص الأسئلة المرسلة في الكويز المخصص.
    """
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
            # إذا كان هناك سؤال سابق قيد التكوين، نحفظه أولاً
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

        # إذا كان مجرد سطر تكميلي لنص السؤال
        if current_question is not None and not omatch and not qmatch:
            current_question += " " + line

    # حفظ آخر سؤال
    save_current_question()

    return questions_data

async def unified_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    هاندلر واحد للرسائل النصية يفرّق بين:
    1) وضع الكويز المخصص (CUSTOM_QUIZ_STATE).
    2) رسائل الكويز الجاهز (STATE_ASK_NUM_QUESTIONS).
    3) التريغرات في المجموعات.
    4) الأوامر الإدارية (في حال الأدمن).
    5) أي أمر آخر.
    """

    user_state = context.user_data.get(CURRENT_STATE_KEY, None)

    # أوامر إدارية إن كان الأدمن
    if update.message.from_user.id == ADMIN_CHAT_ID:
        # مثلاً /total_users, /list_users, /search_user ...
        # تم فصلها في admin_command_handler
        text_cmd = update.message.text.strip().lower()
        if text_cmd.startswith("/total_users") or text_cmd.startswith("/list_users") or text_cmd.startswith("/search_user") or text_cmd.startswith("/all_users_info"):
            await admin_command_handler(update, context)
            return

    # 1) لو المستخدم في وضع الكويز المخصص
    if user_state == CUSTOM_QUIZ_STATE:
        text = update.message.text
        questions_data = parse_custom_questions(text)

        if not questions_data:
            await update.message.reply_text("لم يتم العثور على أسئلة بالصيغة المطلوبة. تأكد من التنسيق.")
            return

        poll_ids = []
        poll_correct_answers = {}
        owner_id = update.message.from_user.id
        chat_id = update.message.chat_id

        # إرسال الأسئلة على شكل Poll
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
        return

    # 2) لو الرسالة في مجموعة وتحوي تريغرات => نفذ start_command
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

    # 4) خلاف ذلك، لا نفعل شيئًا.
    pass

# -------------------------------------------------
# 14) PollAnswerHandlers
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
    app.add_handler(CommandHandler("create_custom_quiz", create_custom_quiz_command))

    # ==== إصلاح ترتيب الهاندلر لإلغاء الكويز قبل العام
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
# 16) دالة بديلة لتشغيل البوت بالميزات نفسها
# -------------------------------------------------
def run_extended_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
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
