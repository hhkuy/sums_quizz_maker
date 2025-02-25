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
    MessageHandler,
    PollAnswerHandler,
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
# 2) توكن البوت - ضع التوكن الخاص بك هنا
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
def fetch_questions(file_path: str):
    """
    جلب ملف الأسئلة من مستودع GitHub بالاعتماد على المسار (file_path).
    يعيد قائمة من القواميس (الأسئلة).
    """
    url = f"{BASE_RAW_URL}/{file_path}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()  # قائمة من القواميس (الأسئلة)
    except Exception as e:
        logger.error(f"Error fetching questions from {url}: {e}")
        return []

def fetch_topics_with_counts():
    """
    جلب ملف الـ topics.json من مستودع GitHub، ثم لكل موضوع فرعي
    نجلب ملف الأسئلة لحساب العدد (count)، ونضيفه إلى بنية البيانات.
    يعيد list[dict] جاهزة للاستخدام.
    """
    try:
        response = requests.get(TOPICS_JSON_URL)
        response.raise_for_status()
        topics_data = response.json()  # القائمة الأساسية للمواضيع

        # إضافة حقل "count" لكل موضوع فرعي
        for topic in topics_data:
            subtopics = topic.get("subTopics", [])
            for sub in subtopics:
                file_path = sub.get("file", "")
                if file_path:
                    questions_list = fetch_questions(file_path)
                    sub["count"] = len(questions_list)
                else:
                    sub["count"] = 0

        return topics_data
    except Exception as e:
        logger.error(f"Error fetching topics: {e}")
        return []

# -------------------------------------------------
# 5) مفاتيح حفظ الحالة واستخدامها
# -------------------------------------------------
TOPICS_KEY = "topics"
CUR_TOPIC_IDX_KEY = "current_topic_index"
CUR_SUBTOPIC_IDX_KEY = "current_subtopic_index"
CURRENT_STATE_KEY = "current_state"
NUM_QUESTIONS_KEY = "num_questions"

STATE_SELECT_TOPIC = "select_topic"
STATE_SELECT_SUBTOPIC = "select_subtopic"
STATE_SUBTOPIC_OPTIONS = "subtopic_options"
STATE_ASK_NUM_QUESTIONS = "ask_num_questions"

ALL_QUESTIONS_LIST = "all_questions_list"   # يخزن جميع أسئلة الموضوع
ALL_QUESTIONS_IDX = "all_questions_index"   # الفهرس الحالي للإرسال الجزئي
BOT_LAST_MESSAGE_ID = "bot_last_message_id" # ليس مفعلاً بقوة الآن, لكن نحتفظ به

# -------------------------------------------------
# 6) إدارة الاختبارات العشوائية (لكل مستخدم على حدة)
# -------------------------------------------------
QUIZ_DATA = "quizzes_data"
POLL_TO_QUIZ_ID = "poll_to_quiz_id"
QUIZ_ID_COUNTER = "quiz_id_counter"

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
    """
    عرض اسم الموضوع الفرعي + عدد الأسئلة بين قوسين.
    """
    keyboard = []
    subtopics = topic.get("subTopics", [])
    for j, sub in enumerate(subtopics):
        sub_name = sub["name"]
        sub_count = sub.get("count", 0)
        btn = InlineKeyboardButton(
            text=f"{sub_name} ({sub_count})",
            callback_data=f"subtopic_{topic_index}_{j}"
        )
        keyboard.append([btn])

    back_btn = InlineKeyboardButton("« رجوع للمواضيع", callback_data="go_back_topics")
    keyboard.append([back_btn])

    return InlineKeyboardMarkup(keyboard)

def generate_subtopic_options_keyboard(t_idx, s_idx):
    """
    ثلاثة أزرار:
      1) إرسال جميع الأسئلة
      2) تحديد عدد الأسئلة (اختبار عشوائي)
      3) رجوع
    """
    btn_all = InlineKeyboardButton("إرسال جميع الأسئلة", callback_data=f"send_all_{t_idx}_{s_idx}")
    btn_random = InlineKeyboardButton("تحديد عدد الأسئلة", callback_data=f"ask_random_{t_idx}_{s_idx}")
    btn_back = InlineKeyboardButton("« رجوع", callback_data=f"go_back_subtopics_{t_idx}")

    keyboard = [
        [btn_all],
        [btn_random],
        [btn_back]
    ]
    return InlineKeyboardMarkup(keyboard)

def generate_send_all_next_keyboard(t_idx, s_idx):
    """
    زر لمتابعة إرسال بقية الأسئلة عند التقطيع
    """
    btn_next = InlineKeyboardButton("إرسال بقية الأسئلة »", callback_data=f"send_all_next_{t_idx}_{s_idx}")
    return InlineKeyboardMarkup([[btn_next]])

# -------------------------------------------------
# 8) أوامر البوت: /start
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /start:
    - نجلب قائمة المواضيع مع عدد الأسئلة الفرعية (مرة واحدة).
    - نعرضها على شكل أزرار.
    """
    if "topics_cached" not in context.bot_data:
        topics_data = fetch_topics_with_counts()
        context.bot_data["topics_cached"] = topics_data
    else:
        topics_data = context.bot_data["topics_cached"]

    if not topics_data:
        await update.message.reply_text(
            "حدث خطأ في جلب المواضيع من GitHub! تأكد من صلاحية الرابط."
        )
        return

    context.user_data[TOPICS_KEY] = topics_data
    context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC

    keyboard = generate_topics_inline_keyboard(topics_data)
    sent_msg = await update.message.reply_text(
        text="مرحبًا بك! اختر الموضوع الرئيسي من القائمة:",
        reply_markup=keyboard
    )

    # لو في مجموعة يمكننا تخزين المعرف إن أردنا لاحقًا
    if update.message.chat.type in ("group", "supergroup"):
        context.user_data[BOT_LAST_MESSAGE_ID] = sent_msg.message_id

# -------------------------------------------------
# 9) أوامر البوت: /help
# -------------------------------------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "الأوامر المتاحة:\n"
        "/start - لبدء اختيار المواضيع\n"
        "/help - عرض هذه الرسالة\n\n"
        "في المجموعات يمكنك منادات البوت بعبارات مثل:\n"
        "بوت سوي اسئلة - بوت الاسئلة - بوت وينك\n"
        "وسيقوم بإظهار قائمة المواضيع للاختيار.\n"
    )
    await update.message.reply_text(help_text)

# -------------------------------------------------
# 10) هاندلر للأزرار (CallbackQueryHandler)
# -------------------------------------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    topics_data = context.user_data.get(TOPICS_KEY, [])

    # ---------------------------
    # 1) اختيار موضوع رئيسي
    # ---------------------------
    if data.startswith("topic_"):
        # data = "topic_<idx>"
        _, idx_str = data.split("_", 1)
        topic_index = int(idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = topic_index
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_SUBTOPIC

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

    # ---------------------------
    # 2) زر الرجوع لقائمة المواضيع
    # ---------------------------
    elif data == "go_back_topics":
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC
        keyboard = generate_topics_inline_keyboard(topics_data)
        await query.message.edit_text(
            text="اختر الموضوع الرئيسي من القائمة:",
            reply_markup=keyboard
        )

    # ---------------------------
    # 3) اختيار موضوع فرعي -> عرض الأزرار الثلاثة
    # ---------------------------
    elif data.startswith("subtopic_"):
        # data = "subtopic_<t_idx>_<s_idx>"
        _, t_idx_str, s_idx_str = data.split("_", 2)
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)

        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CUR_SUBTOPIC_IDX_KEY] = s_idx
        context.user_data[CURRENT_STATE_KEY] = STATE_SUBTOPIC_OPTIONS

        if t_idx < 0 or t_idx >= len(topics_data):
            await query.message.reply_text("خطأ في اختيار الموضوع.")
            return

        subtopics = topics_data[t_idx].get("subTopics", [])
        if s_idx < 0 or s_idx >= len(subtopics):
            await query.message.reply_text("خطأ في اختيار الموضوع الفرعي.")
            return

        subtopic_name = subtopics[s_idx]["name"]
        kb = generate_subtopic_options_keyboard(t_idx, s_idx)
        await query.message.edit_text(
            text=f"الموضوع الفرعي: *{subtopic_name}*\n\nاختر إحدى الخيارات:",
            parse_mode="Markdown",
            reply_markup=kb
        )

    # ---------------------------
    # 4) زر الرجوع لقائمة المواضيع الفرعية
    # ---------------------------
    elif data.startswith("go_back_subtopics_"):
        # data = "go_back_subtopics_<t_idx>"
        _, _, _, t_idx_str = data.split("_", 3)
        t_idx = int(t_idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_SUBTOPIC

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

    # ---------------------------
    # 5) إرسال جميع الأسئلة (Poll Quiz) -> إعداد الإرسال المجزأ
    # ---------------------------
    elif data.startswith("send_all_"):
        # data = "send_all_<t_idx>_<s_idx>"
        _, _, t_idx_str, s_idx_str = data.split("_", 3)
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)

        subtopics = topics_data[t_idx].get("subTopics", [])
        file_path = subtopics[s_idx]["file"]
        questions = fetch_questions(file_path)

        # نخزن في user_data لنتمكن من التقطيع
        context.user_data[ALL_QUESTIONS_LIST] = questions
        context.user_data[ALL_QUESTIONS_IDX] = 0

        await send_all_questions_chunk(update, context, t_idx, s_idx)

    # ---------------------------
    # 6) زر "إرسال بقية الأسئلة"
    # ---------------------------
    elif data.startswith("send_all_next_"):
        # data = "send_all_next_<t_idx>_<s_idx>"
        _, _, _, t_idx_str, s_idx_str = data.split("_", 4)
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)
        await send_all_questions_chunk(update, context, t_idx, s_idx, continuation=True)

    # ---------------------------
    # 7) تحديد عدد الأسئلة (عشوائي) -> ترسل كاختبار Quiz مع نتائج
    # ---------------------------
    elif data.startswith("ask_random_"):
        # data = "ask_random_<t_idx>_<s_idx>"
        _, _, t_idx_str, s_idx_str = data.split("_", 3)
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)

        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CUR_SUBTOPIC_IDX_KEY] = s_idx
        context.user_data[CURRENT_STATE_KEY] = STATE_ASK_NUM_QUESTIONS

        back_btn = InlineKeyboardButton("« رجوع", callback_data=f"subtopic_{t_idx}_{s_idx}")
        kb = InlineKeyboardMarkup([[back_btn]])

        await query.message.edit_text(
            text="أدخل عدد الأسئلة المطلوبة (أرسل رقمًا فقط):",
            reply_markup=kb
        )

    else:
        await query.message.reply_text("لم أفهم هذا الخيار.")

# -------------------------------------------------
# 11) إرسال جميع الأسئلة (Poll Quiz) على دفعات
# -------------------------------------------------
async def send_all_questions_chunk(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   t_idx: int, s_idx: int, continuation=False):
    """
    يرسل 100 سؤال (أو ما تبقى) دفعة واحدة على شكل Poll Quiz.
    - دون احتساب نتائج المستخدمين؛ مجرد إرسال أسئلة.
    - إذا بقيت أسئلة يعرض زر "إرسال بقية الأسئلة".
    - يتم ترقيم الأسئلة تلقائيًا: سؤال #1, #2, ...
    """
    query = update.callback_query
    questions = context.user_data.get(ALL_QUESTIONS_LIST, [])
    start_index = context.user_data.get(ALL_QUESTIONS_IDX, 0)
    chunk_size = 100

    if not questions:
        await query.message.edit_text("لا توجد أسئلة.")
        return

    end_index = min(start_index + chunk_size, len(questions))
    batch = questions[start_index:end_index]

    if not continuation:
        # عدّل الرسالة السابقة للإشارة إلى بدء الإرسال
        await query.message.edit_text("جاري إرسال الأسئلة...")

    chat_id = query.message.chat_id

    # إرسال كل سؤال بشكل Poll Quiz
    for i, q in enumerate(batch, start=start_index + 1):
        raw_text = q.get("question", "سؤال غير متوفر").strip()
        # إزالة الوسوم HTML إن وُجدت
        raw_text = re.sub(r"<.*?>", "", raw_text)

        # إضافة الترقيم
        question_text = f"سؤال #{i}: {raw_text}"

        options = q.get("options", [])
        correct_id = q.get("answer", 0)
        explanation = q.get("explanation", "")

        # ضمان وجود خيارات كافية
        if len(options) < 2:
            options = ["A", "B"]

        # تصحيح المؤشر إن لزم
        if correct_id < 0 or correct_id >= len(options):
            correct_id = 0

        # إرسال الاستفتاء
        await context.bot.send_poll(
            chat_id=chat_id,
            question=question_text,
            options=options,
            type=Poll.QUIZ,
            correct_option_id=correct_id,
            explanation=explanation,
            is_anonymous=False
        )

    # حدّث الفهرس
    context.user_data[ALL_QUESTIONS_IDX] = end_index

    # إذا بقي أسئلة
    if end_index < len(questions):
        kb = generate_send_all_next_keyboard(t_idx, s_idx)
        remaining = len(questions) - end_index
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"تم إرسال {end_index} سؤال. تبقّى {remaining} سؤال.\n"
                 f"اضغط على الزر لمتابعة الإرسال.",
            reply_markup=kb
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="تم الانتهاء من إرسال جميع الأسئلة."
        )
        # إعادة الضبط
        context.user_data[ALL_QUESTIONS_LIST] = []
        context.user_data[ALL_QUESTIONS_IDX] = 0

# -------------------------------------------------
# 12) هاندلر للرسائل النصية (مرحلة "تحديد عدد الأسئلة" + التريجر)
# -------------------------------------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_lower = update.message.text.lower()

    # تريجر في المجموعات
    if update.message.chat.type in ("group", "supergroup"):
        triggers = ["بوت سوي اسئلة", "بوت الاسئلة", "بوت وينك"]
        if any(trig in text_lower for trig in triggers):
            await start_command(update, context)
            return

    user_state = context.user_data.get(CURRENT_STATE_KEY, None)

    # إذا كنا في مرحلة "تحديد عدد الأسئلة" (الاختبار العشوائي)
    if user_state == STATE_ASK_NUM_QUESTIONS:
        # لا نتأكد من الرد على رسالة البوت الأخيرة، نسمح بالإدخال مباشرة
        if not text_lower.isdigit():
            await update.message.reply_text("من فضلك أدخل رقمًا صحيحًا.")
            return

        num_q = int(text_lower)
        if num_q <= 0:
            await update.message.reply_text("العدد يجب أن يكون أكبر من صفر.")
            return

        context.user_data[NUM_QUESTIONS_KEY] = num_q

        # جلب بيانات الموضوع
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
            f"سيتم إرسال {num_q} سؤال بشكل اختبار Quiz.\n"
            "يمكن لأي شخص في المجموعة الإجابة، وسيحصل كل مستخدم على نتيجته عند إكماله جميع الأسئلة."
        )

        chat_id = update.message.chat_id
        if QUIZ_ID_COUNTER not in context.chat_data:
            context.chat_data[QUIZ_ID_COUNTER] = 1
        quiz_id = context.chat_data[QUIZ_ID_COUNTER]
        context.chat_data[QUIZ_ID_COUNTER] += 1

        if QUIZ_DATA not in context.chat_data:
            context.chat_data[QUIZ_DATA] = {}

        # إنشاء كائن الكويز في chat_data
        context.chat_data[QUIZ_DATA][quiz_id] = {
            "poll_ids": [],
            "correct_answers": {},
            "total": num_q,
            "participants": {},
            "chat_id": chat_id
        }

        # إرسال الأسئلة على شكل Poll (Quiz) مع ترقيم تلقائي
        for i, q in enumerate(selected_questions, start=1):
            raw_text = re.sub(r"<.*?>", "", q.get("question", "سؤال؟")).strip()
            # إضافة الترقيم
            question_text = f"سؤال #{i}: {raw_text}"

            options = q.get("options", [])
            correct_id = q.get("answer", 0)
            explanation = q.get("explanation", "")

            # تأكد من عدد الخيارات
            if len(options) < 2:
                options = ["A", "B"]

            if correct_id < 0 or correct_id >= len(options):
                correct_id = 0

            sent_msg = await context.bot.send_poll(
                chat_id=chat_id,
                question=question_text,
                options=options,
                type=Poll.QUIZ,
                correct_option_id=correct_id,
                explanation=explanation,
                is_anonymous=False
            )

            if sent_msg.poll:
                pid = sent_msg.poll.id
                context.chat_data[QUIZ_DATA][quiz_id]["poll_ids"].append(pid)
                context.chat_data[QUIZ_DATA][quiz_id]["correct_answers"][pid] = correct_id

                if POLL_TO_QUIZ_ID not in context.chat_data:
                    context.chat_data[POLL_TO_QUIZ_ID] = {}
                context.chat_data[POLL_TO_QUIZ_ID][pid] = quiz_id

        # إعادة ضبط حالة المستخدم
        context.user_data[CURRENT_STATE_KEY] = None

    else:
        # أي رسالة أخرى ليس لها معالجة
        pass

# -------------------------------------------------
# 13) هاندلر لاستقبال إجابات المستخدم (PollAnswerHandler) في الاختبار العشوائي
# -------------------------------------------------
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند وصول إجابة مستخدم على Poll في وضع "الاختبار العشوائي"،
    نتحقق إن أنجز كل الأسئلة فنرسل نتيجته.
    """
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_options = poll_answer.option_ids

    if POLL_TO_QUIZ_ID not in context.chat_data:
        return
    poll_to_quiz = context.chat_data[POLL_TO_QUIZ_ID]

    if poll_id not in poll_to_quiz:
        return

    quiz_id = poll_to_quiz[poll_id]
    quizzes_data = context.chat_data[QUIZ_DATA]
    if quiz_id not in quizzes_data:
        return

    quiz_info = quizzes_data[quiz_id]
    correct_answers_dict = quiz_info["correct_answers"]
    total_questions = quiz_info["total"]

    if len(selected_options) != 1:
        return

    chosen_index = selected_options[0]
    correct_index = correct_answers_dict.get(poll_id, 0)

    # تحديث بيانات المشارك
    if user_id not in quiz_info["participants"]:
        quiz_info["participants"][user_id] = {
            "answered_count": 0,
            "correct_count": 0
        }

    quiz_info["participants"][user_id]["answered_count"] += 1
    if chosen_index == correct_index:
        quiz_info["participants"][user_id]["correct_count"] += 1

    user_data = quiz_info["participants"][user_id]
    answered = user_data["answered_count"]
    correct = user_data["correct_count"]

    # إذا أنهى هذا المستخدم جميع الأسئلة
    if answered == total_questions:
        correct_num = correct
        wrong_num = total_questions - correct_num
        group_chat_id = quiz_info.get("chat_id", user_id)

        user_mention = f'<a href="tg://user?id={user_id}">{poll_answer.user.first_name}</a>'
        result_msg = (
            f"النتائج للمستخدم {user_mention}:\n"
            f"عدد الأسئلة: {total_questions}\n"
            f"الإجابات الصحيحة: {correct_num}\n"
            f"الإجابات الخاطئة: {wrong_num}\n"
            f"النتيجة النهائية: {correct_num} / {total_questions}"
        )

        await context.bot.send_message(
            chat_id=group_chat_id,
            text=result_msg,
            parse_mode="HTML"
        )

# -------------------------------------------------
# 14) دالة main لتشغيل البوت
# -------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # أوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))

    # أزرار
    app.add_handler(CallbackQueryHandler(callback_handler))

    # رسائل نصية
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # استقبال أجوبة الاستبيان (PollAnswer)
    app.add_handler(PollAnswerHandler(poll_answer_handler))

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
