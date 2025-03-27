# -------------------------------------------------
#   bot.py
#   تم إضافة ميزة تخزين المستخدمين في ملف user.json على GitHub
# -------------------------------------------------

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
# 3) روابط GitHub لجلب/تعديل الملفات
# -------------------------------------------------
BASE_RAW_URL = "https://raw.githubusercontent.com/hhkuy/Sums_Q/main"
TOPICS_JSON_URL = f"{BASE_RAW_URL}/data/topics.json"

# معلومات GitHub الخاصة بملف user.json
GITHUB_TOKEN = "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"
GITHUB_REPO_OWNER = "hhkuy"
GITHUB_REPO_NAME = "sums_quizz_maker"
USER_JSON_PATH = "user.json"

# معرف الأدمن الوحيد الذي يستلم إشعارات انضمام المستخدمين الجدد + تظهر له لوحة تحكم خاصة
ADMIN_CHAT_ID = 912860244

# -------------------------------------------------
# 4) دوال جلب البيانات من GitHub
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
ACTIVE_QUIZ_KEY = "active_quiz"  # سيخزن تفاصيل الكويز الجاهز (poll_ids وغيرها)

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
# 8) دوال خاصة بالتعامل مع user.json في GitHub
# -------------------------------------------------
def get_github_file_info():
    """
    جلب معلومات ملف user.json من GitHub (خصوصاً الـ sha) لتسهيل التحديث.
    """
    api_url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{USER_JSON_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    resp = requests.get(api_url, headers=headers)
    resp.raise_for_status()
    return resp.json()  # يحتوي على معلومات الملف، منها 'sha' و 'content' (base64)

def fetch_users_db():
    """
    جلب محتوى user.json (قائمة المستخدمين) كـ list أو dict من GitHub.
    """
    try:
        file_info = get_github_file_info()
        content_b64 = file_info["content"]
        # في بعض الأحيان يأتي مع علامة سطر جديد
        content_str = base64.b64decode(content_b64).decode('utf-8')
        data = json.loads(content_str)  # يفترض أن الملف مخزن إما في شكل list أو dict
        sha = file_info["sha"]
        return data, sha
    except Exception as e:
        logger.error(f"Error fetching users_db: {e}")
        # لو حدث خطأ، نُرجع قيمة افتراضية
        return [], None

def update_users_db(data, old_sha, commit_message="Update user.json"):
    """
    رفع المحتوى الجديد من user.json إلى GitHub.
    data: يمثل المحتوى الجديد ( list أو dict ).
    old_sha: قيمة sha القديمة للملف.
    """
    api_url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{USER_JSON_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    new_content_str = json.dumps(data, ensure_ascii=False, indent=2)
    new_content_b64 = base64.b64encode(new_content_str.encode('utf-8')).decode('utf-8')

    payload = {
        "message": commit_message,
        "content": new_content_b64,
        "sha": old_sha
    }

    resp = requests.put(api_url, headers=headers, json=payload)
    resp.raise_for_status()  # إذا فشل سيرفع Exception

def ensure_user_in_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يتحقق من وجود المستخدم في user.json، وإذا لم يكن موجوداً، يضيفه.
    يعيد True إذا كان مستخدماً جديداً، False إذا كان مستخدماً قديماً.
    """
    user = update.effective_user
    if not user:
        return False

    # جلب الداتا حالياً
    data, old_sha = fetch_users_db()
    if not isinstance(data, list):
        # لو لم يكن الملف من نوع list، نحوله إلى قائمة
        data = []

    # معلومات المستخدم المطلوب تخزينها
    user_id = user.id
    chat_id = update.effective_chat.id
    username = user.first_name or ""
    user_handle = user.username or ""
    # في بوت التليجرام العادي، غالباً لا يتوفر phone_number أو bio بشكل مباشر.
    # نفترض قيم افتراضية إن لم تتوفر.
    phone_number = "غير متاح"
    bio = "غير متاح"

    # قد نحاول جلب الـ bio باستخدام getChat (قد تعمل مع الحسابات الشخصية في بعض الظروف)
    try:
        chat_obj = context.bot.get_chat(user_id)
        if chat_obj.bio:
            bio = chat_obj.bio
    except:
        pass

    # تاريخ الدخول
    entry_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # نفحص هل المستخدم موجود مسبقاً
    # حسب الطلب: "اذا كان الشخص متواجد نفس المعلومات مثلا المعرف او معرف المحادثة"
    # سنعتبر (user_id) أساس التحقق بشكل أساسي، وإن أردت التحقق من اليوزرنيم/المعرف أو chat_id أيضاً فلا بأس.
    user_exists = False
    for u in data:
        # نتحقق من ID أو المعرف أو chat_id
        if (
            u.get("user_id") == user_id
            or (u.get("user_handle") and u["user_handle"] == user_handle and user_handle != "")
            or (u.get("chat_id") and u["chat_id"] == chat_id)
        ):
            user_exists = True
            break

    if not user_exists:
        # مستخدم جديد
        new_user_info = {
            "user_id": user_id,
            "username": username,
            "user_handle": user_handle,
            "phone_number": phone_number,
            "chat_id": chat_id,
            "bio": bio,
            "entry_date": entry_date
        }
        data.append(new_user_info)
        # حدّث الملف
        commit_msg = f"Add new user: {user_id}"
        update_users_db(data, old_sha, commit_msg)
        return True
    else:
        return False

def get_total_users_count():
    """
    يعيد عدد المستخدمين المسجلين حالياً.
    """
    data, _ = fetch_users_db()
    if isinstance(data, list):
        return len(data)
    return 0

def get_all_users_info():
    """
    يعيد قائمة بجميع المستخدمين (كتنسيق نصي بسيط).
    """
    data, _ = fetch_users_db()
    if not isinstance(data, list):
        return "لا يوجد مستخدمون في قاعدة البيانات حالياً."

    if len(data) == 0:
        return "لا يوجد مستخدمون في قاعدة البيانات حالياً."

    lines = []
    for i, u in enumerate(data, start=1):
        lines.append(
            f"{i}) ID: {u.get('user_id')} | اسم: {u.get('username')} | معرف: @{u.get('user_handle')} | شاتID: {u.get('chat_id')} | دخول: {u.get('entry_date')}"
        )
    return "\n".join(lines)

def search_users(keyword: str):
    """
    البحث عن مستخدمين في user.json عن طريق أي نص (في اليوزرنيم أو اليوزر_هاندل أو الـ ID...الخ).
    يعيد نص يحتوي على النتائج.
    """
    data, _ = fetch_users_db()
    if not isinstance(data, list):
        return "لا يوجد مستخدمون في قاعدة البيانات."

    keyword_lower = keyword.lower()
    results = []

    for u in data:
        # نفحص أي حقل نصي
        if (
            keyword_lower in str(u.get("user_id", "")).lower()
            or keyword_lower in str(u.get("username", "")).lower()
            or keyword_lower in str(u.get("user_handle", "")).lower()
            or keyword_lower in str(u.get("chat_id", "")).lower()
            or keyword_lower in str(u.get("phone_number", "")).lower()
            or keyword_lower in str(u.get("bio", "")).lower()
        ):
            results.append(u)

    if not results:
        return "لم يتم العثور على أي مطابق."

    lines = []
    for i, u in enumerate(results, start=1):
        lines.append(
            f"{i}) ID: {u.get('user_id')} | اسم: {u.get('username')} | معرف: @{u.get('user_handle')} | شاتID: {u.get('chat_id')} | دخول: {u.get('entry_date')}"
        )

    return "\n".join(lines)

# -------------------------------------------------
# 9) أوامر البوت: /start
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /start:
    - نقوم بتخزين المستخدم إن كان جديداً (في user.json).
    - نعرض زرين: 1) اختر كويز جاهز. 2) أنشئ كويز مخصص.
    - إذا كان المستخدم هو الأدمن (ADMIN_CHAT_ID) نعرض له زر إضافي للدخول إلى لوحة الإدارة.
    """
    # تحقق من المستخدم وأضفه إن كان جديداً
    is_new_user = ensure_user_in_db(update, context)

    # لو مستخدم جديد، نرسل إشعاراً إلى الأدمن فقط
    if is_new_user:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"انضم مستخدم جديد!\nID: {update.effective_user.id}\nاسم: {update.effective_user.first_name}\nيوزر: @{update.effective_user.username}"
            )
        except:
            pass

    # بناء أزرار البداية
    keyboard = [
        [InlineKeyboardButton("اختر كويز جاهز", callback_data="start_ready_quiz")],
        [InlineKeyboardButton("أنشئ كويز مخصص", callback_data="start_custom_quiz")]
    ]

    # إذا كان المستخدم هو الأدمن، نضيف زر لوحة الإدارة
    if update.effective_chat.id == ADMIN_CHAT_ID:
        keyboard.append([InlineKeyboardButton("لوحة الإدارة", callback_data="admin_panel")])

    markup = InlineKeyboardMarkup(keyboard)

    welcome_message = (
        "هلا بيك نورت بوت حصرة ال dog 😵‍💫🚬\n\n"
        "تم صنعه من قِبل : [@h_h_k9](https://t.me/h_h_k9) 🙏🏻\n\n"
        "البوت تكدر تستعمله لصنع كويز جاهز (يستخدم أسئلة فاينلات) ✅ أو صنع كويز مخصص (ترسل الأسئلة للبوت وفق التعليمات) ⬆️👍🏻\n\n"
        "يمكنك استعمال البوت دايركت أو في كروبات (لو رفعته كأدمن بصلاحية إرسال الرسائل).\n\n"
        "ونطلب منكم الدعاء وشكراً ✨\n\n"
        "هسة أختار احد الاختيارين:"
    )

    await update.message.reply_text(
        welcome_message,
        parse_mode="Markdown",
        reply_markup=markup
    )

# -------------------------------------------------
# 9.1) المنطق الأصلي لجلب المواضيع وعرضها (كان في start_command_flow سابقًا)
#     (تم دمج المهمة الأساسية الآن في الدوال الأخرى)
# -------------------------------------------------

# -------------------------------------------------
# 10) أوامر البوت: /help
# -------------------------------------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "الأوامر المتاحة:\n"
        "/start - لعرض الأزرار (اختر كويز جاهز، أنشئ كويز مخصص)\n"
        "/help - عرض هذه الرسالة\n\n"
        "يمكنك أيضًا مناداتي في المجموعات وسيعمل البوت عند كتابة:\n"
        "«بوت سوي اسئلة» أو «بوت الاسئلة» أو «بوت وينك».\n"
    )
    await update.message.reply_text(help_text)

# -------------------------------------------------
# 11) دوال للكويز الجاهز
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
# 12) هاندلر للأزرار (CallbackQueryHandler)
# -------------------------------------------------
ADMIN_STATE_SEARCH = "admin_search_state"

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

    # لوحة الإدارة (للأدمن فقط)
    elif data == "admin_panel":
        if query.message.chat_id == ADMIN_CHAT_ID:
            admin_keyboard = [
                [InlineKeyboardButton("عدد المستخدمين", callback_data="admin_count_users")],
                [InlineKeyboardButton("عرض جميع المستخدمين", callback_data="admin_list_users")],
                [InlineKeyboardButton("بحث عن مستخدم", callback_data="admin_search_users")]
            ]
            await query.message.reply_text("لوحة الإدارة:", reply_markup=InlineKeyboardMarkup(admin_keyboard))
        else:
            await query.message.reply_text("غير مصرح لك!")
        return

    # أوامر لوحة الإدارة
    elif data == "admin_count_users":
        if query.message.chat_id == ADMIN_CHAT_ID:
            count = get_total_users_count()
            await query.message.reply_text(f"عدد المستخدمين الكلي: {count}")
        else:
            await query.message.reply_text("غير مصرح لك!")
        return

    elif data == "admin_list_users":
        if query.message.chat_id == ADMIN_CHAT_ID:
            info_text = get_all_users_info()
            await query.message.reply_text(info_text)
        else:
            await query.message.reply_text("غير مصرح لك!")
        return

    elif data == "admin_search_users":
        if query.message.chat_id == ADMIN_CHAT_ID:
            await query.message.reply_text("أرسل كلمة للبحث عن المستخدمين (ID/اسم/معرف/رقم...).")
            context.user_data[CURRENT_STATE_KEY] = ADMIN_STATE_SEARCH
        else:
            await query.message.reply_text("غير مصرح لك!")
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
# 13) دوال لإنشاء الكويز المخصص
# -------------------------------------------------
CUSTOM_QUIZ_STATE = "custom_quiz_state"
ACTIVE_CUSTOM_QUIZ_KEY = "active_custom_quiz"

async def create_custom_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    أمر صريح: /create_custom_quiz
    يعرض التعليمات حول كيفية إرسال الأسئلة مع *** لتمييز الإجابة الصحيحة.
    """
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

async def create_custom_quiz_command_from_callback(query, context: ContextTypes.DEFAULT_TYPE):
    """
    استدعاء مباشرةً من الزر "أنشئ كويز مخصص" بدلاً من كتابة /create_custom_quiz.
    """
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

async def custom_quiz_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند الضغط على زر (إلغاء) في الكويز المخصص.
    """
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_custom_quiz":
        context.user_data[CURRENT_STATE_KEY] = None
        await query.message.edit_text("تم الإلغاء. يمكنك استخدام /create_custom_quiz مجددًا لاحقًا.")
    else:
        await query.message.reply_text("خيار غير مفهوم.")

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

# -------------------------------------------------
# 14) هاندلر موحد للرسائل النصية
# -------------------------------------------------
async def unified_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    هاندلر واحد للرسائل النصية يفرّق بين:
    1) وضع الكويز المخصص (CUSTOM_QUIZ_STATE).
    2) رسائل الكويز الجاهز (STATE_ASK_NUM_QUESTIONS).
    3) التريغرات في المجموعات.
    4) أوامر لوحة الإدارة (في حالة البحث).
    5) أي نص آخر.
    """
    user_state = context.user_data.get(CURRENT_STATE_KEY, None)

    # 1) لو المستخدم في وضع الكويز المخصص
    if user_state == CUSTOM_QUIZ_STATE:
        await handle_custom_quiz_text(update, context)
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

    # 4) لوحة الإدارة - البحث عن مستخدم
    if user_state == ADMIN_STATE_SEARCH and update.effective_chat.id == ADMIN_CHAT_ID:
        keyword = update.message.text.strip()
        results_text = search_users(keyword)
        await update.message.reply_text(results_text)
        # نعيد الحالة إلى None بعد البحث
        context.user_data[CURRENT_STATE_KEY] = None
        return

    # 5) خلاف ذلك، لا نفعل شيئًا (أو يمكنك الرد برسالة).
    pass

async def handle_custom_quiz_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يعالج نص الرسالة إذا كان المستخدم في وضع CUSTOM_QUIZ_STATE.
    """
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

async def handle_ready_quiz_num_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يعالج رسالة تحتوي على عدد الأسئلة للكويز الجاهز (STATE_ASK_NUM_QUESTIONS).
    """
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
# 15) هاندلر لاستقبال إجابات المستخدم (PollAnswerHandler) للكويز الجاهز
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

    # نتحقق أن المجيب هو نفسه مالك الكويز
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
# 16) هاندلر لاستقبال إجابات الاستفتاء في الكويز المخصص
# -------------------------------------------------
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

    # نتحقق أن المجيب هو نفسه مالك الكويز
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
# 17) الدوال الرئيسية لتشغيل البوت
# -------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # الأوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("create_custom_quiz", create_custom_quiz_command))

    # ===== هاندلر زر الإلغاء للكويز المخصص =====
    app.add_handler(CallbackQueryHandler(custom_quiz_callback_handler, pattern="^(cancel_custom_quiz)$"))

    # هاندلر عام للأزرار
    app.add_handler(CallbackQueryHandler(callback_handler))

    # هاندلر موحد للرسائل النصية
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unified_message_handler))

    # PollAnswer (الكويز الجاهز + الكويز المخصص)
    app.add_handler(PollAnswerHandler(poll_answer_handler))
    app.add_handler(PollAnswerHandler(custom_quiz_poll_answer_handler))

    logger.info("Bot is running on Railway...")
    app.run_polling()

# يمكنك استخدام هذه الدالة بدلاً من main() لو أردت
def run_extended_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("create_custom_quiz", create_custom_quiz_command))

    # نفس المبدأ: اجعل هاندلر إلغاء الكويز قبل الهاندلر العام
    app.add_handler(CallbackQueryHandler(custom_quiz_callback_handler, pattern="^(cancel_custom_quiz)$"))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unified_message_handler))

    app.add_handler(PollAnswerHandler(poll_answer_handler))
    app.add_handler(PollAnswerHandler(custom_quiz_poll_answer_handler))

    logger.info("Extended Bot is running ...")
    app.run_polling()

if __name__ == "__main__":
    main()
