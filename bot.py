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
# 1) Logging إعداد نظام
# -------------------------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------------------------------------
# 2) ضع توكن البوت هنا
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
    """
    جلب ملف topics.json من GitHub على شكل list[dict].
    """
    try:
        response = requests.get(TOPICS_JSON_URL)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching topics: {e}")
        return []

def fetch_questions(file_path: str):
    """
    جلب ملف الأسئلة (JSON) بالاعتماد على المسار من المستودع.
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
# 5) مفاتيح الحالة والتخزين
# -------------------------------------------------
STATE_SELECT_TOPIC = "select_topic"
STATE_SELECT_SUBTOPIC = "select_subtopic"
STATE_WAITING_SUBTOPIC_ACTION = "waiting_subtopic_action"
STATE_WAITING_RANDOM_NUMBER = "waiting_random_number"

TOPICS_KEY = "topics"
CURRENT_STATE_KEY = "current_state"
CUR_TOPIC_IDX_KEY = "current_topic_idx"
CUR_SUBTOPIC_IDX_KEY = "current_subtopic_idx"
CUR_SUBTOPIC_QUESTIONS = "current_subtopic_questions"  # نخزن هنا أسئلة الموضوع الفرعي

WAITING_FOR_REPLY_MSG_ID = "waiting_for_reply_msg_id"  # في chat_data

# بيانات الاختبار العشوائي في المجموعات
ACTIVE_QUIZ_KEY = "active_quiz"

# -------------------------------------------------
# 6) إنشاء الكيبوردات (Inline Keyboards)
# -------------------------------------------------
def generate_topics_inline_keyboard(topics_data):
    """
    إنشاء كيبورد لاختيار المواضيع الرئيسية.
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
    إنشاء كيبورد لاختيار المواضيع الفرعية (مع ظهور عدد الأسئلة بجانب الاسم) + زر الرجوع للمواضيع.
    """
    keyboard = []
    subtopics = topic.get("subTopics", [])

    for j, sub in enumerate(subtopics):
        file_path = sub["file"]
        questions = fetch_questions(file_path)
        num_questions = len(questions)
        btn_text = f"{sub['name']} (عددها: {num_questions})"
        btn = InlineKeyboardButton(
            text=btn_text,
            callback_data=f"subtopic_{topic_index}_{j}"
        )
        keyboard.append([btn])

    # زر الرجوع لقائمة المواضيع الرئيسية
    back_btn = InlineKeyboardButton("« رجوع للمواضيع", callback_data="go_back_topics")
    keyboard.append([back_btn])
    return InlineKeyboardMarkup(keyboard)

def generate_subtopic_actions_keyboard(topic_index, sub_index):
    """
    عند اختيار موضوع فرعي، نعرض 3 أزرار:
    1) إرسال جميع الأسئلة (Poll REGULAR).
    2) تحديد عدد الأسئلة (اختبار عشوائي بميزة الصح/الخطأ).
    3) زر الرجوع لقائمة المواضيع الفرعية.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="1) إرسال جميع الأسئلة",
                callback_data=f"send_all_{topic_index}_{sub_index}_start"
            )
        ],
        [
            InlineKeyboardButton(
                text="2) تحديد عدد الأسئلة (اختبار عشوائي)",
                callback_data=f"random_quiz_{topic_index}_{sub_index}"
            )
        ],
        [
            InlineKeyboardButton(
                text="« رجوع للمواضيع الفرعية",
                callback_data=f"go_back_subtopics_{topic_index}"
            )
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def generate_send_all_continue_keyboard(topic_index, sub_index, next_chunk):
    """
    عند إرسال جميع الأسئلة على شكل دفعات، نعرض زر متابعة للدفعة التالية.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="متابعة إرسال بقية الأسئلة",
                callback_data=f"send_all_{topic_index}_{sub_index}_{next_chunk}"
            )
        ]
    ])

# -------------------------------------------------
# 7) الدوال الأساسية للأوامر
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يبدأ البوت بعرض قائمة المواضيع الرئيسية.
    """
    # نجلب قائمة المواضيع مرة واحدة ونضعها في user_data
    topics_data = fetch_topics()
    context.user_data[TOPICS_KEY] = topics_data

    if not topics_data:
        await update.message.reply_text("عذراً، حدث خطأ في جلب المواضيع من GitHub.")
        return

    context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC
    keyboard = generate_topics_inline_keyboard(topics_data)
    await update.message.reply_text(
        text="مرحباً بك! اختر الموضوع الرئيسي:",
        reply_markup=keyboard
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "الأوامر المتاحة:\n"
        "/start - بدء البوت واختيار المواضيع\n"
        "/help - عرض هذه الرسالة\n\n"
        "في المجموعات، يمكن مناداتي بعبارات مثل:\n"
        "«بوت سوي اسئلة»، «بوت الاسئلة»، «بوت وينك»\n"
        "وسأعرض قائمة المواضيع.\n"
    )
    await update.message.reply_text(help_text)

# -------------------------------------------------
# 8) التعامل مع ضغط الأزرار (CallbackQueryHandler)
# -------------------------------------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # رجوع لقائمة المواضيع الرئيسية
    if data == "go_back_topics":
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC
        topics_data = context.user_data.get(TOPICS_KEY, [])
        keyboard = generate_topics_inline_keyboard(topics_data)
        await query.message.edit_text(
            text="اختر الموضوع الرئيسي:",
            reply_markup=keyboard
        )
        return

    # رجوع لقائمة المواضيع الفرعية
    if data.startswith("go_back_subtopics_"):
        # data مثل: go_back_subtopics_{topic_idx}
        _, t_idx_str = data.split("_subtopics_")
        t_idx = int(t_idx_str)
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_SUBTOPIC
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx

        topics_data = context.user_data.get(TOPICS_KEY, [])
        if 0 <= t_idx < len(topics_data):
            chosen_topic = topics_data[t_idx]
            kb = generate_subtopics_inline_keyboard(chosen_topic, t_idx)
            msg_text = (
                f"اختر الموضوع الفرعي لـ: *{chosen_topic['topicName']}*\n\n"
                f"{chosen_topic.get('description', '')}"
            )
            await query.message.edit_text(
                text=msg_text,
                parse_mode="Markdown",
                reply_markup=kb
            )
        else:
            await query.message.edit_text("خيار غير صحيح.")
        return

    # اختيار موضوع رئيسي
    if data.startswith("topic_"):
        # data مثل: topic_{topic_index}
        _, idx_str = data.split("_")
        t_idx = int(idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_SUBTOPIC

        topics_data = context.user_data.get(TOPICS_KEY, [])
        if t_idx < 0 or t_idx >= len(topics_data):
            await query.message.reply_text("خيار غير صحيح.")
            return

        chosen_topic = topics_data[t_idx]
        sub_kb = generate_subtopics_inline_keyboard(chosen_topic, t_idx)
        msg_text = (
            f"اختر الموضوع الفرعي لـ: *{chosen_topic['topicName']}*\n\n"
            f"{chosen_topic.get('description', '')}"
        )
        await query.message.edit_text(
            text=msg_text,
            parse_mode="Markdown",
            reply_markup=sub_kb
        )
        return

    # اختيار موضوع فرعي -> عرض الأزرار الثلاث
    if data.startswith("subtopic_"):
        # data مثل: subtopic_{topic_idx}_{subtopic_idx}
        _, t_idx_str, s_idx_str = data.split("_")
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CUR_SUBTOPIC_IDX_KEY] = s_idx
        context.user_data[CURRENT_STATE_KEY] = STATE_WAITING_SUBTOPIC_ACTION

        topics_data = context.user_data.get(TOPICS_KEY, [])
        if t_idx < 0 or t_idx >= len(topics_data):
            await query.message.reply_text("خيار غير صحيح.")
            return
        subtopics = topics_data[t_idx].get("subTopics", [])
        if s_idx < 0 or s_idx >= len(subtopics):
            await query.message.reply_text("خيار غير صحيح.")
            return

        # جلب الأسئلة وحفظها في الذاكرة (حتى لا نجلبها مجدداً)
        file_path = subtopics[s_idx]["file"]
        questions = fetch_questions(file_path)
        context.user_data[CUR_SUBTOPIC_QUESTIONS] = questions

        subtopic_name = subtopics[s_idx]["name"]
        num_q = len(questions)

        text_msg = (
            f"اختر أحد الخيارات لموضوع فرعي: *{subtopic_name}*\n\n"
            f"عدد الأسئلة المتوفر: {num_q}"
        )
        await query.message.edit_text(
            text=text_msg,
            parse_mode="Markdown",
            reply_markup=generate_subtopic_actions_keyboard(t_idx, s_idx)
        )
        return

    # إرسال جميع الأسئلة (Poll REGULAR) - البداية (start)
    if data.startswith("send_all_") and data.endswith("_start"):
        # مثال data: send_all_{t_idx}_{s_idx}_start
        parts = data.split("_")
        # ["send", "all", t_idx, s_idx, "start"]
        t_idx = int(parts[2])
        s_idx = int(parts[3])

        # إعادة ضبط الدفعة الأولى
        chunk_index = 0

        # إرسال نص "جاري الإرسال..."
        await query.message.edit_text("جاري إرسال الأسئلة ...")

        # استدعاء دالة إرسال الدفعة
        await send_all_questions_in_chunks(query, context, t_idx, s_idx, chunk_index)
        return

    # إرسال جميع الأسئلة (Poll REGULAR) - الدفعات التالية
    if data.startswith("send_all_"):
        # قد يكون data: send_all_{t_idx}_{s_idx}_{chunk_index}
        parts = data.split("_")
        if len(parts) == 5:
            # ["send","all", t_idx, s_idx, chunk_index]
            t_idx = int(parts[2])
            s_idx = int(parts[3])
            chunk_index = int(parts[4])

            await query.message.edit_text("جاري إرسال الدفعة التالية...")
            await send_all_questions_in_chunks(query, context, t_idx, s_idx, chunk_index)
        return

    # اختبار عشوائي
    if data.startswith("random_quiz_"):
        # data: random_quiz_{t_idx}_{s_idx}
        _, t_idx_str, s_idx_str = data.split("_")
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)

        # نطلب من المستخدم إدخال العدد بالرد على هذه الرسالة
        context.user_data[CURRENT_STATE_KEY] = STATE_WAITING_RANDOM_NUMBER
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CUR_SUBTOPIC_IDX_KEY] = s_idx

        # نمسح الكيبورد السابقة ونضع رسالة جديدة
        await query.message.edit_text(
            text="أرسل عدد الأسئلة المطلوبة (ردًا على هذه الرسالة)."
        )
        # نخزّن الـ message_id حتى لا نقبل مدخلات إلا بالرد عليه
        context.chat_data[WAITING_FOR_REPLY_MSG_ID] = query.message.message_id
        return

    # إذا لم نفهم الخيار
    await query.message.reply_text("لم أفهم هذا الخيار.")

# -------------------------------------------------
# 9) دالة إرسال جميع الأسئلة على دفعات (Regular Poll)
# -------------------------------------------------
async def send_all_questions_in_chunks(query, context, t_idx, s_idx, chunk_index):
    chat_id = query.message.chat_id
    questions = context.user_data.get(CUR_SUBTOPIC_QUESTIONS, [])
    total_questions = len(questions)
    chunk_size = 100

    start_idx = chunk_index * chunk_size
    end_idx = start_idx + chunk_size
    subset = questions[start_idx:end_idx]

    if not subset:
        # لا توجد أسئلة في هذه الدفعة -> ربما انتهى الإرسال
        await context.bot.send_message(
            chat_id=chat_id,
            text="تم الانتهاء من إرسال جميع الأسئلة."
        )
        return

    # إرسال كل سؤال كـ Poll REGULAR بدون صح/خطأ
    for q in subset:
        q_text = re.sub(r"<.*?>", "", q.get("question", "سؤال بدون نص")).strip()
        options = q.get("options", [])

        # Poll عادي
        await context.bot.send_poll(
            chat_id=chat_id,
            question=q_text,
            options=options,
            is_anonymous=False,
            type=Poll.REGULAR
        )

        await asyncio.sleep(0.3)  # فاصل زمني بسيط لتفادي مشاكل التليجرام

    # إذا بقيت أسئلة بعدها، نعرض زر المتابعة
    if end_idx < total_questions:
        next_chunk = chunk_index + 1
        kb = generate_send_all_continue_keyboard(t_idx, s_idx, next_chunk)
        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"تم إرسال {len(subset)} سؤال. هل تريد المتابعة؟",
            reply_markup=kb
        )
    else:
        # لا مزيد من الأسئلة
        await context.bot.send_message(
            chat_id=chat_id,
            text="تم الانتهاء من إرسال جميع الأسئلة."
        )

# -------------------------------------------------
# 10) استقبال الرسائل النصية (MessageHandler)
# -------------------------------------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_lower = update.message.text.lower()

    # في المجموعات: إذا نادوا البوت بهذا النص، كأنهم نفذوا /start
    if update.message.chat.type in ("group", "supergroup"):
        triggers = ["بوت سوي اسئلة", "بوت الاسئلة", "بوت وينك"]
        if any(t in text_lower for t in triggers):
            await start_command(update, context)
            return

    # إذا كنا في حالة انتظار عدد الأسئلة للاختبار العشوائي
    current_state = context.user_data.get(CURRENT_STATE_KEY)
    if current_state == STATE_WAITING_RANDOM_NUMBER:
        waiting_msg_id = context.chat_data.get(WAITING_FOR_REPLY_MSG_ID)
        if not waiting_msg_id:
            # غير مهيأ
            return

        # يجب أن تكون الرسالة ردًا على رسالة البوت
        if (not update.message.reply_to_message) or (update.message.reply_to_message.message_id != waiting_msg_id):
            await update.message.reply_text("رقم غير صحيح. يجب الرد على رسالة البوت الأخيرة.")
            return

        # تحقق من أن المدخل رقم
        num_txt = update.message.text.strip()
        if not num_txt.isdigit():
            await update.message.reply_text("رقم غير صحيح. أرسل رقمًا فقط.")
            return

        num_questions = int(num_txt)
        if num_questions <= 0:
            await update.message.reply_text("العدد يجب أن يكون أكبر من صفر.")
            return

        # مسح حالة الانتظار
        context.user_data[CURRENT_STATE_KEY] = None
        context.chat_data.pop(WAITING_FOR_REPLY_MSG_ID, None)

        # لدينا t_idx, s_idx
        t_idx = context.user_data.get(CUR_TOPIC_IDX_KEY, 0)
        s_idx = context.user_data.get(CUR_SUBTOPIC_IDX_KEY, 0)
        questions = context.user_data.get(CUR_SUBTOPIC_QUESTIONS, [])

        if num_questions > len(questions):
            await update.message.reply_text(f"لا يوجد سوى {len(questions)} سؤال في هذا الموضوع الفرعي.")
            return

        # اختيار عشوائي
        random.shuffle(questions)
        selected = questions[:num_questions]

        await update.message.reply_text(
            f"جاري إرسال {num_questions} سؤال (اختبار Quiz). كل مستخدم في المجموعة يمكنه المشاركة، وستظهر نتيجة كل مستخدم عند انتهائه."
        )

        # إنشاء كائن للاختبار في chat_data
        chat_id = update.message.chat_id
        active_quiz = {
            "poll_correct_answers": {},  # poll_id -> correct_index
            "total_polls": num_questions,
            "users": {},  # user_id -> {"answered_count", "correct_count", "wrong_count", "answered_polls": set()}
            "chat_id": chat_id
        }
        context.chat_data[ACTIVE_QUIZ_KEY] = active_quiz

        # إرسال الأسئلة بشكل Quiz
        for q in selected:
            q_text = re.sub(r"<.*?>", "", q.get("question", "سؤال بدون نص")).strip()
            options = q.get("options", [])
            correct_id = q.get("answer", 0)
            explanation = q.get("explanation", "")

            poll_msg = await context.bot.send_poll(
                chat_id=chat_id,
                question=q_text,
                options=options,
                type=Poll.QUIZ,
                correct_option_id=correct_id,
                explanation=explanation,
                is_anonymous=False
            )
            if poll_msg.poll is not None:
                poll_id = poll_msg.poll.id
                active_quiz["poll_correct_answers"][poll_id] = correct_id

            await asyncio.sleep(0.3)

        return

    # ليس لدينا حالة خاصة، نتجاهل أو لا نرد
    # pass

# -------------------------------------------------
# 11) استقبال إجابات الاستطلاعات (PollAnswerHandler)
# -------------------------------------------------
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    poll_id = poll_answer.poll_id
    user_id = poll_answer.user.id
    chosen_options = poll_answer.option_ids

    active_quiz = context.chat_data.get(ACTIVE_QUIZ_KEY)
    if not active_quiz:
        return  # لا يوجد اختبار حالي

    # تحقق أن هذا الاستفتاء ينتمي لاختبارنا
    if poll_id not in active_quiz["poll_correct_answers"]:
        return

    # جلب بيانات المستخدم أو إنشاؤها
    user_data = active_quiz["users"].get(user_id, {
        "answered_count": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "answered_polls": set()
    })

    # إذا المستخدم أجاب سابقاً على هذا السؤال
    if poll_id in user_data["answered_polls"]:
        return

    user_data["answered_polls"].add(poll_id)
    user_data["answered_count"] += 1

    correct_idx = active_quiz["poll_correct_answers"][poll_id]
    if len(chosen_options) == 1:
        chosen_idx = chosen_options[0]
        if chosen_idx == correct_idx:
            user_data["correct_count"] += 1
        else:
            user_data["wrong_count"] += 1

    # تحديت الداتا
    active_quiz["users"][user_id] = user_data

    # إذا المستخدم أكمل كل الأسئلة
    total_polls = active_quiz["total_polls"]
    if user_data["answered_count"] == total_polls:
        correct = user_data["correct_count"]
        wrong = user_data["wrong_count"]
        user_mention = f'<a href="tg://user?id={user_id}">{poll_answer.user.first_name}</a>'
        msg = (
            f"لقد أكمل {user_mention} الإجابة على {total_polls} سؤال.\n"
            f"الإجابات الصحيحة: {correct}\n"
            f"الإجابات الخاطئة: {wrong}\n"
            f"النتيجة: {correct} / {total_polls}"
        )
        # إرسال النتيجة في المجموعة
        quiz_chat_id = active_quiz.get("chat_id")
        if quiz_chat_id:
            await context.bot.send_message(
                chat_id=quiz_chat_id,
                text=msg,
                parse_mode="HTML"
            )
        else:
            # إذا لم يتوفر لدينا chat_id
            pass

# -------------------------------------------------
# 12) دالة main لتشغيل البوت
# -------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # أوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))

    # الكول باك للأزرار
    app.add_handler(CallbackQueryHandler(callback_handler))

    # استقبال الرسائل النصية
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # استقبال أجوبة الاستطلاع (PollAnswer)
    app.add_handler(PollAnswerHandler(poll_answer_handler))

    logger.info("Bot is running...")
    app.run_polling()

# -------------------------------------------------
# تشغيل البوت
# -------------------------------------------------
if __name__ == "__main__":
    main()
