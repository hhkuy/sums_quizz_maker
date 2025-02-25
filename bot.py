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
#    سنجلب قائمة المواضيع ثم نجلب عدد الأسئلة
#    لكل موضوع فرعي ونخزّنه حتى نعرضه بجانب اسم
#    الموضوع الفرعي.
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
# مفاتيح لحفظ بيانات الاختيار داخل user_data (أو chat_data)
TOPICS_KEY = "topics"               # قائمة المواضيع كاملة
CUR_TOPIC_IDX_KEY = "current_topic_index"
CUR_SUBTOPIC_IDX_KEY = "current_subtopic_index"
CURRENT_STATE_KEY = "current_state"
NUM_QUESTIONS_KEY = "num_questions"

STATE_SELECT_TOPIC = "select_topic"
STATE_SELECT_SUBTOPIC = "select_subtopic"
STATE_SUBTOPIC_OPTIONS = "subtopic_options"
STATE_ASK_NUM_QUESTIONS = "ask_num_questions"

# مفاتيح أخرى
ALL_QUESTIONS_LIST = "all_questions_list"  # لتخزين الأسئلة عند اختيار "إرسال الجميع"
ALL_QUESTIONS_IDX = "all_questions_index"  # لتخزين الفهرس الحالي في الإرسال المجزّأ
BOT_LAST_MESSAGE_ID = "bot_last_message_id"  # لتتبع آخر رسالة أرسلها البوت في المجموعة

# -------------------------------------------------
# 6) إدارة الاختبارات العشوائية: سنستخدم chat_data
#    حتى يتمكن أكثر من مستخدم من خوض الاختبار في نفس المجموعة
#    بنفس الوقت ويحصل كل منهم على نتيجته.
# -------------------------------------------------
QUIZ_DATA = "quizzes_data"  # مفتاح في chat_data لخزن كل الكويزات
POLL_TO_QUIZ_ID = "poll_to_quiz_id"  # خريطة من poll_id إلى quiz_id
QUIZ_ID_COUNTER = "quiz_id_counter"  # عدّاد لتمييز كل كويز

# هيكلية تخزين الكويز في chat_data[QUIZ_DATA][quiz_id]:
# {
#    "poll_ids": [... list of polls belonging to this quiz ...],
#    "correct_answers": { poll_id: correct_option_id, ... },
#    "total": عدد_الأسئلة,
#    "participants": {
#        user_id: {
#            "answered_count": 0,
#            "correct_count": 0
#        },
#        ...
#    }
# }

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
    سنعرض (اسم الفرع + عدد الأسئلة).
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

    # زر الرجوع لقائمة المواضيع
    back_btn = InlineKeyboardButton("« رجوع للمواضيع", callback_data="go_back_topics")
    keyboard.append([back_btn])

    return InlineKeyboardMarkup(keyboard)

def generate_subtopic_options_keyboard(t_idx, s_idx):
    """
    عند اختيار موضوع فرعي، نظهر 3 أزرار:
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
    زر لإرسال بقية الأسئلة في حال كانت > 100
    """
    btn_next = InlineKeyboardButton("إرسال بقية الأسئلة »", callback_data=f"send_all_next_{t_idx}_{s_idx}")
    return InlineKeyboardMarkup([[btn_next]])

# -------------------------------------------------
# 8) أوامر البوت: /start
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /start:
    - نجلب قائمة المواضيع مع عدد الأسئلة الفرعية ونخزنها في bot_data (أو user_data).
    - نعرضها على شكل أزرار.
    """
    # نجلب المواضيع مرة واحدة ونخزنها في bot_data لضمان عدم تكرار الجلب
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

    # نخزنها أيضًا في user_data للمستخدم الحالي لإدارة التصفح
    context.user_data[TOPICS_KEY] = topics_data
    context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC

    keyboard = generate_topics_inline_keyboard(topics_data)
    sent_msg = await update.message.reply_text(
        text="مرحبًا بك! اختر الموضوع الرئيسي من القائمة:",
        reply_markup=keyboard
    )

    # حفظ معرف رسالة البوت في حالة المجموعة
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
        "في المجموعات يمكن منادات البوت بالعبارات:\n"
        "«بوت سوي اسئلة» أو «بوت الاسئلة» أو «بوت وينك» وسيظهر لك قائمة المواضيع.\n"
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

    # 1) اختيار موضوع رئيسي
    if data.startswith("topic_"):
        _, idx_str = data.split("_")
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

    # 2) زر الرجوع لقائمة المواضيع
    elif data == "go_back_topics":
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC
        keyboard = generate_topics_inline_keyboard(topics_data)

        await query.message.edit_text(
            text="اختر الموضوع الرئيسي من القائمة:",
            reply_markup=keyboard
        )

    # 3) اختيار موضوع فرعي -> عرض الأزرار الثلاثة
    elif data.startswith("subtopic_"):
        _, t_idx_str, s_idx_str = data.split("_")
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

    # 4) زر الرجوع لقائمة المواضيع الفرعية
    elif data.startswith("go_back_subtopics_"):
        _, t_idx_str = data.split("_subtopics_")
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

    # 5) إرسال جميع الأسئلة (T/F) -> إعداد الإرسال المجزأ
    elif data.startswith("send_all_"):
        _, t_idx_str, s_idx_str = data.split("_")
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)

        subtopics = topics_data[t_idx].get("subTopics", [])
        file_path = subtopics[s_idx]["file"]
        questions = fetch_questions(file_path)

        # نخزن قائمة الأسئلة في user_data
        context.user_data[ALL_QUESTIONS_LIST] = questions
        context.user_data[ALL_QUESTIONS_IDX] = 0  # البداية

        # أرسل أول دفعة
        await send_all_questions_chunk(update, context, t_idx, s_idx)

    # 6) زر "إرسال بقية الأسئلة"
    elif data.startswith("send_all_next_"):
        _, t_idx_str, s_idx_str = data.split("_")[2:]
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)
        await send_all_questions_chunk(update, context, t_idx, s_idx, continuation=True)

    # 7) تحديد عدد الأسئلة (عشوائي)
    elif data.startswith("ask_random_"):
        _, t_idx_str, s_idx_str = data.split("_")
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)

        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CUR_SUBTOPIC_IDX_KEY] = s_idx
        context.user_data[CURRENT_STATE_KEY] = STATE_ASK_NUM_QUESTIONS

        # إنشاء زر رجوع يعود إلى قائمة الخيارات الثلاث
        back_btn = InlineKeyboardButton(
            "« رجوع",
            callback_data=f"subtopic_{t_idx}_{s_idx}"
        )
        kb = InlineKeyboardMarkup([[back_btn]])

        await query.message.edit_text(
            text="أدخل عدد الأسئلة المطلوبة (أرسل رقمًا فقط):",
            reply_markup=kb
        )

    else:
        await query.message.reply_text("لم أفهم هذا الخيار.")

# -------------------------------------------------
# 11) دالة مساعدة لإرسال الأسئلة على شكل T/F مجزأة
# -------------------------------------------------
async def send_all_questions_chunk(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   t_idx: int, s_idx: int, continuation=False):
    """
    يرسل 100 سؤال (أو ما تبقى) دفعة واحدة على شكل تصويت T/F.
    عند الانتهاء، إذا بقي أسئلة، يظهر زر لمتابعة الإرسال.
    إذا لا يوجد أسئلة متبقية، يظهر رسالة انتهاء.
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

    # إذا كنا في بداية الإرسال وليس متابعة
    if not continuation:
        await query.message.edit_text("جاري إرسال الأسئلة...")

    chat_id = query.message.chat_id

    # إرسال كل سؤال بشكل Poll T/F (بدون انتظار النتيجة)
    for q in batch:
        question_text = q.get("question", "سؤال غير متوفر").strip()
        # إزالة الوسوم HTML
        question_text = re.sub(r"<.*?>", "", question_text)
        correct_answer = q.get("answer", 0)  # يفترض 0 -> صح ، 1 -> خطأ
        # لضمان بقية الحقول إن وجدت
        explanation = q.get("explanation", "")

        # إرسال تصويت
        await context.bot.send_poll(
            chat_id=chat_id,
            question=question_text,
            options=["صح", "خطأ"],
            type=Poll.QUIZ,
            correct_option_id=correct_answer,
            explanation=explanation,
            is_anonymous=False
        )

    context.user_data[ALL_QUESTIONS_IDX] = end_index

    # إذا انتهينا من الدفعة
    if end_index < len(questions):
        # بقي المزيد
        kb = generate_send_all_next_keyboard(t_idx, s_idx)
        remaining = len(questions) - end_index
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"تم إرسال {end_index} سؤال. تبقّى {remaining} سؤال.\nاضغط على الزر لمتابعة الإرسال.",
            reply_markup=kb
        )
    else:
        # انتهينا
        await context.bot.send_message(
            chat_id=chat_id,
            text="تم الانتهاء من إرسال جميع الأسئلة."
        )
        # إعادة الضبط
        context.user_data[ALL_QUESTIONS_LIST] = []
        context.user_data[ALL_QUESTIONS_IDX] = 0

# -------------------------------------------------
# 12) هاندلر للرسائل النصية (خاصة بعد مطالبة عدد الأسئلة + تريجر المجموعات)
# -------------------------------------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_lower = update.message.text.lower()

    # في المجموعات: إذا احتوت الرسالة على أي من العبارات التالية، نفذ /start
    if update.message.chat.type in ("group", "supergroup"):
        triggers = ["بوت سوي اسئلة", "بوت الاسئلة", "بوت وينك"]
        if any(trig in text_lower for trig in triggers):
            await start_command(update, context)
            return

    user_state = context.user_data.get(CURRENT_STATE_KEY, None)

    # إذا كنا في مرحلة طلب عدد الأسئلة (للاختبار العشوائي)
    if user_state == STATE_ASK_NUM_QUESTIONS:
        # التحقق هل هي رقم صحيح؟
        if not text_lower.isdigit():
            # إذا في مجموعة، نتحقق هل هذا رد على رسالة البوت أساسًا
            if update.message.chat.type in ("group", "supergroup"):
                # يجب الرد على آخر رسالة للبوت
                bot_last_msg_id = context.user_data.get(BOT_LAST_MESSAGE_ID)
                if (update.message.reply_to_message is None or
                    update.message.reply_to_message.message_id != bot_last_msg_id):
                    await update.message.reply_text("رقم غير صحيح. يجب الرد على رسالة البوت الأخيرة.")
                    return

            await update.message.reply_text("من فضلك أدخل رقمًا صحيحًا.")
            return

        # تحقق من الرد الصحيح في المجموعات
        if update.message.chat.type in ("group", "supergroup"):
            bot_last_msg_id = context.user_data.get(BOT_LAST_MESSAGE_ID)
            if (update.message.reply_to_message is None or
                update.message.reply_to_message.message_id != bot_last_msg_id):
                await update.message.reply_text("رقم غير صحيح. يجب الرد على رسالة البوت الأخيرة.")
                return

        num_q = int(text_lower)
        if num_q <= 0:
            await update.message.reply_text("العدد يجب أن يكون أكبر من صفر.")
            return

        context.user_data[NUM_QUESTIONS_KEY] = num_q

        # نجلب بيانات الموضوع والفرع
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

        # خلط واختيار عينة
        random.shuffle(questions)
        selected_questions = questions[:num_q]

        await update.message.reply_text(
            f"سيتم إرسال {num_q} سؤال بشكل اختبار Quiz.\n"
            "يمكن لأي شخص في المجموعة الإجابة، وكل مستخدم سيحصل على نتيجته الخاصة عند إتمامه جميع الأسئلة."
        )

        # أنشئ معرفًا فريدًا للكويز
        if QUIZ_ID_COUNTER not in context.chat_data:
            context.chat_data[QUIZ_ID_COUNTER] = 1
        quiz_id = context.chat_data[QUIZ_ID_COUNTER]
        context.chat_data[QUIZ_ID_COUNTER] += 1

        # أنشئ بنية الكويز في chat_data
        if QUIZ_DATA not in context.chat_data:
            context.chat_data[QUIZ_DATA] = {}
        context.chat_data[QUIZ_DATA][quiz_id] = {
            "poll_ids": [],
            "correct_answers": {},
            "total": num_q,
            "participants": {}
        }

        # إرسال الأسئلة
        chat_id = update.message.chat_id
        for q in selected_questions:
            q_text = re.sub(r"<.*?>", "", q.get("question", "سؤال؟")).strip()
            options = q.get("options", [])
            correct_id = q.get("answer", 0)
            explanation = q.get("explanation", "")

            sent_msg = await context.bot.send_poll(
                chat_id=chat_id,
                question=q_text,
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

                # خريطة poll_id -> quiz_id
                if POLL_TO_QUIZ_ID not in context.chat_data:
                    context.chat_data[POLL_TO_QUIZ_ID] = {}
                context.chat_data[POLL_TO_QUIZ_ID][pid] = quiz_id

        # إعادة ضبط الحالة
        context.user_data[CURRENT_STATE_KEY] = None

    else:
        # أي رسالة أخرى لا نفعل بها شيئًا
        pass

# -------------------------------------------------
# 13) هاندلر لاستقبال إجابات المستخدم (PollAnswerHandler)
# -------------------------------------------------
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    كلما أجاب مستخدم على أحد الاستفتاءات (الـ Poll),
    نقوم بتخزين إجابته في chat_data، وعند اكتمال عدد
    الإجابات للمستخدم (أي أجاب على كل أسئلة هذا الكويز)
    نرسل نتيجته في المجموعة.
    """
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_options = poll_answer.option_ids  # قائمة بالـ indices التي اختارها المستخدم

    # نحتاج إلى إيجاد الكويز المرتبط بهذا الـ poll_id
    if POLL_TO_QUIZ_ID not in context.chat_data:
        return
    poll_to_quiz = context.chat_data[POLL_TO_QUIZ_ID]

    if poll_id not in poll_to_quiz:
        return

    quiz_id = poll_to_quiz[poll_id]
    quizzes_data = context.chat_data[QUIZ_DATA]  # dict
    if quiz_id not in quizzes_data:
        return

    quiz_info = quizzes_data[quiz_id]
    correct_answers_dict = quiz_info["correct_answers"]
    total_questions = quiz_info["total"]

    if len(selected_options) != 1:
        # نفترض سؤال باختيار واحد فقط
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

    # إذا أنهى هذا المستخدم جميع الأسئلة في هذا الكويز
    if answered == total_questions:
        # إرسال النتيجة
        correct_num = correct
        wrong_num = total_questions - correct_num
        chat_id = poll_answer.user.id  # لو أردنا الإرسال للخاص؟
        # المطلوب حسب الطلب: "بعد أن يُنهي المستخدم يرسل النتيجة في نفس المجموعة"
        # لكننا لا نعرف آيدي المجموعة هنا بشكل يقيني، سنخزنها حين إرسال الكويز.
        # الحل: نرسل إلى آخر مكان انطلقت منه الأسئلة (وهذا غالبًا المجموعة).
        # في هذه الحالة سنحتاج حفظ chat_id للكويز أيضًا عند الإنشاء.
        # لكي نضمن الإرسال في المجموعة الأصلية.

        # بدّلنا ونخزّن chat_id في quiz_info عند إنشائه بالرسائل.
        # ولكن الكود الحالي لا يخزن chat_id. فلنعدله:
        # => سنفترض أننا نستخدم poll_answer.user.id للإرسال الخاص!
        # أو نفترض أن آخر رسالة بالاختبار كانت بنفس المجموعة.

        # لتبسيط التنفيذ: نرسل النتيجة في كلتا الحالتين إلى الـ user_id (خاص) إذا أردت:
        # ولكن الطلب صريح: "في المجموعة" .. إذن نحتاج حفظه أثناء الإرسال:

        # سنفعل التالي:
        # 1) أثناء إرسال الكويز العشوائي، نخزن chat_id في quiz_info.
        # 2) هنا نستخرجه.

        group_chat_id = quiz_info.get("chat_id")
        if not group_chat_id:
            # إذا غير موجود، لن نستطيع الإرسال للمجموعة، سنرسل في الخاص كحل بديل
            group_chat_id = user_id

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
        # نزيل المستخدم من participants حتى لا يعاد إرسال النتيجة مرة أخرى
        # لو حاول إعادة التصويت (لكن غالباً لا يستطيع).
        # على كل حال يمكننا تركها أو مسحها:
        # del quiz_info["participants"][user_id]

# -------------------------------------------------
# 14) تعديل بسيط: عند إنشاء الكويز العشوائي نخزن chat_id
#     لكي يستخدمه poll_answer_handler في إرسال النتيجة
# -------------------------------------------------
# سنعدل دالة استقبال العدد (message_handler) في فقرة إنشاء الكويز:
# ... (تم التعديل بالفعل أدناه)

# -------------------------------------------------
# 15) دالة main لتشغيل البوت
# -------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ربط الأوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))

    # أزرار (CallbackQuery)
    app.add_handler(CallbackQueryHandler(callback_handler))

    # استقبال الرسائل النصية (عدد الأسئلة + تريجر المجموعات)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # استقبال أجوبة الاستفتاء (PollAnswer)
    app.add_handler(PollAnswerHandler(poll_answer_handler))

    logger.info("Bot is running...")
    app.run_polling()

# تعديل ضمن نفس الملف (نحتاجه في إنشاء الكويز):
# سنعيد تعريف هذه الدالة هنا لكي تضمِّن chat_id في quiz_info:
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_lower = update.message.text.lower()

    # في المجموعات: إذا احتوت الرسالة على أي من العبارات التالية، نفذ /start
    if update.message.chat.type in ("group", "supergroup"):
        triggers = ["بوت سوي اسئلة", "بوت الاسئلة", "بوت وينك"]
        if any(trig in text_lower for trig in triggers):
            await start_command(update, context)
            return

    user_state = context.user_data.get(CURRENT_STATE_KEY, None)

    if user_state == STATE_ASK_NUM_QUESTIONS:
        if not text_lower.isdigit():
            if update.message.chat.type in ("group", "supergroup"):
                bot_last_msg_id = context.user_data.get(BOT_LAST_MESSAGE_ID)
                if (update.message.reply_to_message is None or
                    update.message.reply_to_message.message_id != bot_last_msg_id):
                    await update.message.reply_text("رقم غير صحيح. يجب الرد على رسالة البوت الأخيرة.")
                    return
            await update.message.reply_text("من فضلك أدخل رقمًا صحيحًا.")
            return

        if update.message.chat.type in ("group", "supergroup"):
            bot_last_msg_id = context.user_data.get(BOT_LAST_MESSAGE_ID)
            if (update.message.reply_to_message is None or
                update.message.reply_to_message.message_id != bot_last_msg_id):
                await update.message.reply_text("رقم غير صحيح. يجب الرد على رسالة البوت الأخيرة.")
                return

        num_q = int(text_lower)
        if num_q <= 0:
            await update.message.reply_text("العدد يجب أن يكون أكبر من صفر.")
            return

        context.user_data[NUM_QUESTIONS_KEY] = num_q

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
            "يمكن لأي شخص في المجموعة الإجابة، وسيحصل كل مستخدم على نتيجته عند إكماله كل الأسئلة."
        )

        # تجهيز الكويز في chat_data
        chat_id = update.message.chat_id
        if QUIZ_ID_COUNTER not in context.chat_data:
            context.chat_data[QUIZ_ID_COUNTER] = 1
        quiz_id = context.chat_data[QUIZ_ID_COUNTER]
        context.chat_data[QUIZ_ID_COUNTER] += 1

        if QUIZ_DATA not in context.chat_data:
            context.chat_data[QUIZ_DATA] = {}

        context.chat_data[QUIZ_DATA][quiz_id] = {
            "poll_ids": [],
            "correct_answers": {},
            "total": num_q,
            "participants": {},
            "chat_id": chat_id  # حفظ معرف المجموعة/المكان
        }

        # إرسال الأسئلة
        for q in selected_questions:
            q_text = re.sub(r"<.*?>", "", q.get("question", "سؤال؟")).strip()
            options = q.get("options", [])
            correct_id = q.get("answer", 0)
            explanation = q.get("explanation", "")

            sent_msg = await context.bot.send_poll(
                chat_id=chat_id,
                question=q_text,
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

        # إعادة ضبط الحالة
        context.user_data[CURRENT_STATE_KEY] = None

    else:
        # لا شيء
        pass

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # أوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))

    # أزرار
    app.add_handler(CallbackQueryHandler(callback_handler))

    # رسائل نصية
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # إجابات الاستبيان
    app.add_handler(PollAnswerHandler(poll_answer_handler))

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
