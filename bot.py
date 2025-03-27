import logging
import requests
import json
import random
import re
import asyncio
import os
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
# 2) توكن البوت
# -------------------------------------------------
BOT_TOKEN = "7633072361:AAHnzREYTKKRFiTiq7HDZBalnwnmgivY8_I"

# -------------------------------------------------
# 3) روابط GitHub لجلب الملفات
# -------------------------------------------------
BASE_RAW_URL = "https://raw.githubusercontent.com/hhkuy/Sums_Q/main"
TOPICS_JSON_URL = f"{BASE_RAW_URL}/data/topics.json"

# -------------------------------------------------
# ملف المستخدمين (user.json) في نفس مسار bot.py
# -------------------------------------------------
USERS_JSON_FILE = "user.json"

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

# مفاتيح إضافية
ACTIVE_QUIZ_KEY = "active_quiz"

# -------------------------------------------------
# ثوابت/مفاتيح الكويز المخصص
# -------------------------------------------------
CUSTOM_QUIZ_STATE = "custom_quiz_state"
ACTIVE_CUSTOM_QUIZ_KEY = "active_custom_quiz"

# -------------------------------------------------
# معرف الإدمن الوحيد الذي تصله إشعارات الانضمام
# -------------------------------------------------
ADMIN_ID = 912860244

# -------------------------------------------------
# دوال التعامل مع user.json
# -------------------------------------------------
def load_users_json():
    """قراءة ملف user.json وإعادته كقائمة/قاموس."""
    if not os.path.isfile(USERS_JSON_FILE):
        return {}
    try:
        with open(USERS_JSON_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_users_json(data):
    """حفظ قاموس المستخدمين في ملف user.json."""
    with open(USERS_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def register_user_if_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يتحقق إن كان المستخدم جديدًا، فإن كان كذلك يتم تخزينه في user.json
    ويرسل إشعارًا للإدمن بقدوم مستخدم جديد.
    """
    user = update.effective_user
    user_id = user.id

    # نحاول جلب معلومات إضافية (bio) من get_chat
    chat_info = await context.bot.get_chat(user_id)
    bio = chat_info.bio if hasattr(chat_info, "bio") and chat_info.bio else ""

    # بناء معلومات المستخدم
    username = user.username if user.username else ""
    first_name = user.first_name if user.first_name else ""
    last_name = user.last_name if user.last_name else ""
    full_name = (first_name + " " + last_name).strip()

    # قد لا نحصل على رقم الهاتف إلا إذا كان مشتركًا بتطبيق تيليجرام برقم أو شاركنا رقمًا
    # يمكننا وضع phone = "" كإفتراض.
    phone_number = ""  # لا تتوفر عادة من دون مشاركة أو getChatMember التفصيلية
    # (يمكن التخصيص حسب الحاجة)

    # chat_id = update.effective_chat.id  <-- هذا لو كانت محادثة خاصة
    # لكننا نريد "private chat id" إن وجد. عند /start غالبًا يكون محادثة خاصة => نفس user_id في الخاص
    # إذا المحادثة خاصة:
    chat_id = update.effective_chat.id if update.effective_chat else ""

    # قراءة قائمة المستخدمين
    data = load_users_json()

    # إذا كان موجودًا، لا نفعل شيئًا
    if str(user_id) in data:
        return  # مستخدم قديم

    # مستخدم جديد => نضيفه
    data[str(user_id)] = {
        "full_name": full_name,
        "username": username,
        "phone": phone_number,
        "chat_id": chat_id,
        "user_id": user_id,
        "bio": bio,
        "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # حفظ
    save_users_json(data)

    # إشعار الإدمن بوصول مستخدم جديد (لأن هذا مستخدم جديد)
    if ADMIN_ID is not None:
        new_user_msg = (
            f"انضم مستخدم جديد:\n\n"
            f"الاسم: {full_name}\n"
            f"المعرف: @{username}\n"
            f"UserID: {user_id}\n"
            f"البايو: {bio}\n"
            f"وقت الانضمام: {data[str(user_id)]['joined_at']}\n\n"
            f"إجمالي المستخدمين الآن: {len(data)}"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=new_user_msg)

# -------------------------------------------------
# 7) دوال لإنشاء الأزرار (InlineKeyboard)
# -------------------------------------------------
def generate_topics_inline_keyboard(topics_data):
    keyboard = []
    for i, topic in enumerate(topics_data):
        btn = InlineKeyboardButton(
            text=topic["topicName"],
            callback_data=f"topic_{i}"
        )
        keyboard.append([btn])
    return InlineKeyboardMarkup(keyboard)


def generate_subtopics_inline_keyboard(topic, topic_index):
    keyboard = []
    subtopics = topic.get("subTopics", [])
    for j, sub in enumerate(subtopics):
        btn = InlineKeyboardButton(
            text=sub["name"],
            callback_data=f"subtopic_{topic_index}_{j}"
        )
        keyboard.append([btn])

    back_btn = InlineKeyboardButton("« رجوع للمواضيع", callback_data="go_back_topics")
    keyboard.append([back_btn])

    return InlineKeyboardMarkup(keyboard)

def generate_admin_inline_keyboard():
    """
    قائمة أزرار بسيطة للإدمن فقط: عرض العدد الكلي، عرض الكل، البحث...
    """
    kb = [
        [InlineKeyboardButton("عدد المستخدمين", callback_data="admin_show_user_count")],
        [InlineKeyboardButton("عرض جميع المستخدمين", callback_data="admin_show_all_users")],
        [InlineKeyboardButton("بحث عن مستخدم", callback_data="admin_search_user")],
        [InlineKeyboardButton("رجوع", callback_data="admin_go_back")]
    ]
    return InlineKeyboardMarkup(kb)

# -------------------------------------------------
# 8) أوامر البوت: /start
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /start:
    - نتحقق من تسجيل المستخدم.
    - نعرض زرين: (اختر كويز جاهز) و (أنشئ كويز مخصص).
    - إذا كان المستخدم إدمن، نعرض زر (إدارة البوت) إضافيًا.
    """
    # تسجيل المستخدم (لو جديد يرسل إشعار للإدمن)
    await register_user_if_new(update, context)

    keyboard = [
        [InlineKeyboardButton("اختر كويز جاهز", callback_data="start_ready_quiz")],
        [InlineKeyboardButton("أنشئ كويز مخصص", callback_data="start_custom_quiz")]
    ]

    # إذا كان المستخدم هو الإدمن، نضيف زر "إدارة البوت"
    if update.effective_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("إدارة البوت", callback_data="admin_menu")])

    markup = InlineKeyboardMarkup(keyboard)

    welcome_message = (
        "هلا بيك نورت بوت حصرة ال dog 😵‍💫🚬\n\n"
        "تم صنعه من قِبل : [@h_h_k9](https://t.me/h_h_k9) 🙏🏻\n\n"
        "البوت تكدر تستعمله لصنع كوز جاهز ( يستخدم اسئلة فاينلات ) ✅ او صنع كوز مخصص ( ترسل الاسئلة للبوت وفق التعليمات و هو يتكفل بيهن و يصنعلك الاسئلة ) ⬆️👍🏻\n\n"
        "البوت تكدر تستعمله دايركت او كروبات ( ترفعه ادمن مع صلاحيات ارسال الرسائل ) اذا حبيتوا تسون كوز جماعي 🔥\n\n"
        "ونطلب منكم الدعاء وشكراً ✨\n\n"
        "هسة أختار احد الاختيارين و كول يا الله و صلِ على محمد و أل محمد :"
    )

    await update.message.reply_text(
        welcome_message,
        parse_mode="Markdown",
        reply_markup=markup
    )

async def start_command_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    المنطق الأصلي لجلب المواضيع من GitHub وعرضها.
    """
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
# 9) /help
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
# 10) هاندلر للأزرار (CallbackQueryHandler)
# -------------------------------------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # زر "اختر كويز جاهز"
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

    # زر "أنشئ كويز مخصص"
    elif data == "start_custom_quiz":
        await create_custom_quiz_command_from_callback(query, context)
        return

    # زر "إدارة البوت" (للإدمن فقط)
    elif data == "admin_menu":
        if query.from_user.id == ADMIN_ID:
            kb = generate_admin_inline_keyboard()
            await query.message.reply_text("القائمة الإدارية:", reply_markup=kb)
        else:
            await query.message.reply_text("ليست لديك صلاحيات الإدارة.")
        return

    # الأزرار الإدارية
    elif data == "admin_show_user_count":
        if query.from_user.id == ADMIN_ID:
            users_data = load_users_json()
            count = len(users_data)
            await query.message.reply_text(f"عدد المستخدمين: {count}")
        else:
            await query.message.reply_text("ليست لديك صلاحيات الإدارة.")
        return

    elif data == "admin_show_all_users":
        if query.from_user.id == ADMIN_ID:
            users_data = load_users_json()
            if not users_data:
                await query.message.reply_text("لا يوجد مستخدمون مسجّلون بعد.")
                return
            msg_lines = []
            for uid, info in users_data.items():
                line = f"{uid} => {info['full_name']} (@{info['username']})"
                msg_lines.append(line)
            out_msg = "\n".join(msg_lines)
            await query.message.reply_text(f"جميع المستخدمين:\n\n{out_msg}")
        else:
            await query.message.reply_text("ليست لديك صلاحيات الإدارة.")
        return

    elif data == "admin_search_user":
        if query.from_user.id == ADMIN_ID:
            # نطلب من الأدمن إرسال كلمة البحث
            await query.message.reply_text("أرسل كلمة البحث للبحث عن مستخدم بالاسم أو المعرف:")
            # نضع حالة خاصة للمستخدم
            context.user_data["admin_search_mode"] = True
        else:
            await query.message.reply_text("ليست لديك صلاحيات الإدارة.")
        return

    elif data == "admin_go_back":
        # رجوع من القائمة الإدارية
        if query.from_user.id == ADMIN_ID:
            # نعيد إظهار زر الإدارة من جديد
            keyboard = [
                [InlineKeyboardButton("اختر كويز جاهز", callback_data="start_ready_quiz")],
                [InlineKeyboardButton("أنشئ كويز مخصص", callback_data="start_custom_quiz")],
                [InlineKeyboardButton("إدارة البوت", callback_data="admin_menu")]
            ]
            markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("تم الرجوع للقائمة الرئيسية:", reply_markup=markup)
        else:
            await query.message.reply_text("ليست لديك صلاحيات الإدارة.")
        return

    # اختيار موضوع رئيسي
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

# -------------------------------------------------
# هاندلر زر إلغاء الكويز المخصص قبل الهاندلر العام
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
# 11) أمر /create_custom_quiz
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

        # سطر تكميلي لنص السؤال
        if current_question is not None and not omatch and not qmatch:
            current_question += " " + line

    # آخر سؤال
    save_current_question()

    return questions_data

# -------------------------------------------------
# 12) هاندلر موحد للرسائل النصية
# -------------------------------------------------
async def unified_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state = context.user_data.get(CURRENT_STATE_KEY, None)

    # 1) إذا كان المستخدم في وضع الكويز المخصص
    if user_state == CUSTOM_QUIZ_STATE:
        await handle_custom_quiz_text(update, context)
        return

    # 2) إذا كانت الرسالة في مجموعة وتحوي تريغرات
    if update.message.chat.type in ("group", "supergroup"):
        text_lower = update.message.text.lower()
        triggers = ["بوت سوي اسئلة", "بوت الاسئلة", "بوت وينك"]
        if any(trig in text_lower for trig in triggers):
            await start_command(update, context)
            return

    # 3) إذا كنا في مرحلة طلب عدد الأسئلة (الكويز الجاهز)
    if user_state == STATE_ASK_NUM_QUESTIONS:
        await handle_ready_quiz_num_questions(update, context)
        return

    # 4) في حال كان الإدمن في وضع "admin_search_mode"
    if context.user_data.get("admin_search_mode") and update.message.from_user.id == ADMIN_ID:
        # نبحث في user.json
        search_key = update.message.text.strip().lower()
        users_data = load_users_json()
        results = []
        for uid, info in users_data.items():
            # نتحقق من fullname أو username أو bio
            name_match = (search_key in info["full_name"].lower()) if info["full_name"] else False
            user_match = (search_key in info["username"].lower()) if info["username"] else False
            bio_match = (search_key in info["bio"].lower()) if info["bio"] else False
            if name_match or user_match or bio_match:
                results.append(f"{uid} => {info['full_name']} (@{info['username']})")

        if not results:
            await update.message.reply_text("لا توجد نتائج مطابقة.")
        else:
            out_msg = "\n".join(results)
            await update.message.reply_text(f"نتائج البحث:\n{out_msg}")

        # إطفاء وضع البحث
        context.user_data["admin_search_mode"] = False
        return

    # 5) أي شيء آخر لا نفعل به شيئًا
    pass


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
# 13) PollAnswer (الكويز الجاهز)
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
# 14) PollAnswer (الكويز المخصص)
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
# 15) الدالة الرئيسية main
# -------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # الأوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("create_custom_quiz", create_custom_quiz_command))

    # زر إلغاء الكويز المخصص قبل الهاندلر العام
    app.add_handler(CallbackQueryHandler(custom_quiz_callback_handler, pattern="^(cancel_custom_quiz)$"))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # هاندلر موحد للرسائل النصية
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unified_message_handler))

    # PollAnswer
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

    # زر إلغاء قبل الهاندلر العام
    app.add_handler(CallbackQueryHandler(custom_quiz_callback_handler, pattern="^(cancel_custom_quiz)$"))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unified_message_handler))

    app.add_handler(PollAnswerHandler(poll_answer_handler))
    app.add_handler(PollAnswerHandler(custom_quiz_poll_answer_handler))

    logger.info("Extended Bot is running ...")
    app.run_polling()


if __name__ == "__main__":
    main()
