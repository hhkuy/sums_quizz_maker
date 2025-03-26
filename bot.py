import logging
import requests
import json
import random
import re
import asyncio

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
# 3) روابط GitHub لجلب الملفات
# -------------------------------------------------
BASE_RAW_URL = "https://raw.githubusercontent.com/hhkuy/Sums_Q/main"
TOPICS_JSON_URL = f"{BASE_RAW_URL}/data/topics.json"

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
# 8) أوامر البوت: /start (معدل ليعرض زرين: "كويز جاهز" و "كويز مخصص")
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /start:
    - نعرض زرين: 1) اختر كويز جاهز. 2) أنشئ كويز مخصص.
    """
    keyboard = [
        [
            InlineKeyboardButton("اختر كويز جاهز", callback_data="start_ready_quiz"),
            InlineKeyboardButton("أنشئ كويز مخصص", callback_data="start_custom_quiz")
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "مرحبًا بك!\nاختر أحد الخيارين أدناه:",
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
        # تنفيذ المنطق الأصلي: عرض قائمة المواضيع من GitHub
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
# 11) ثوابت ووظائف للكويز المخصص
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
# 12) هاندلر موحد للرسائل النصية
# -------------------------------------------------
async def unified_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    هاندلر واحد للرسائل النصية يفرّق بين:
    1) وضع الكويز المخصص (CUSTOM_QUIZ_STATE).
    2) رسائل الكويز الجاهز (STATE_ASK_NUM_QUESTIONS).
    3) التريغرات في المجموعات.
    4) أي أمر آخر.
    """

    # 1) لو المستخدم في وضع الكويز المخصص
    user_state = context.user_data.get(CURRENT_STATE_KEY, None)
    if user_state == CUSTOM_QUIZ_STATE:
        # تحليل النص باعتباره أسئلة مخصصة
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
        # نعالج الرسالة على أنها عدد الأسئلة للكويز الجاهز
        await handle_ready_quiz_num_questions(update, context)
        return

    # 4) خلاف ذلك، لا نفعل شيئًا.
    # (يمكن إضافة منطق إضافي حسب رغبتك)
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

    # بعد الإرسال، نخرج من حالة السؤال عن عدد الأسئلة
    context.user_data[CURRENT_STATE_KEY] = None

# -------------------------------------------------
# 13) هاندلر لاستقبال إجابات المستخدم (PollAnswerHandler) للكويز الجاهز
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


# -------------------------------------------------
# 14) هاندلر لاستقبال إجابات الاستفتاء في الكويز المخصص
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

    # أزرار
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CallbackQueryHandler(custom_quiz_callback_handler, pattern="^(cancel_custom_quiz)$"))

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

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CallbackQueryHandler(custom_quiz_callback_handler, pattern="^(cancel_custom_quiz)$"))

    # هاندلر موحد للرسائل
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unified_message_handler))

    # PollAnswer
    app.add_handler(PollAnswerHandler(poll_answer_handler))
    app.add_handler(PollAnswerHandler(custom_quiz_poll_answer_handler))

    logger.info("Extended Bot is running ...")
    app.run_polling()


if __name__ == "__main__":
    main()
