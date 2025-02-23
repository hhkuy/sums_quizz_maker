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
    Poll,
    WebAppInfo
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
# 5) مفاتيح لحفظ الحالة في context.user_data و context.chat_data
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

# سيتم تخزين بيانات الكويز في context.chat_data حتى يتمكن الجميع من المشاركة
ACTIVE_QUIZ_KEY = "active_quiz"

# -------------------------------------------------
# 6) دوال لإنشاء الأزرار (InlineKeyboard)
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
    إنشاء إنلاين كيبورد لقائمة المواضيع الفرعية مع زر الرجوع.
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
# 7) أمر البوت: /start
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /start يتم جلب المواضيع من GitHub وعرضها كأزرار.
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
        text="مرحبًا بك! اختر الموضوع الرئيسي من القائمة:",
        reply_markup=keyboard
    )

# -------------------------------------------------
# 8) أمر البوت: /help
# -------------------------------------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "الأوامر المتاحة:\n"
        "/start - لبدء اختيار المواضيع\n"
        "/help - عرض هذه الرسالة\n"
        "/medsums - فتح موقع MedSums داخل البوت\n\n"
        "كما يمكنك مناداتي في المجموعات باستخدام:\n"
        "«بوت سوي اسئلة» أو «بوت الاسئلة» أو «بوت وينك».\n"
    )
    await update.message.reply_text(help_text)

# -------------------------------------------------
# 9) أمر البوت: /medsums
# -------------------------------------------------
async def medsums_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /medsums يتم إرسال رسالة تحتوي على زر الويب آب،
    بحيث يظهر للمستخدم زر لفتح موقع MedSums داخل البوت.
    """
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="اضغط هنا لفتح MedSums", web_app=WebAppInfo(url="https://sites.google.com/view/medsums"))]
    ])
    await update.message.reply_text(
        text="يمكنك فتح موقع MedSums داخل البوت من خلال الضغط على الزر أدناه:",
        reply_markup=keyboard
    )

# -------------------------------------------------
# 10) هاندلر للأزرار (CallbackQueryHandler)
# -------------------------------------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

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

    # زر الرجوع لقائمة المواضيع
    elif data == "go_back_topics":
        context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC
        topics_data = context.user_data.get(TOPICS_KEY, [])
        keyboard = generate_topics_inline_keyboard(topics_data)
        await query.message.edit_text(
            text="اختر الموضوع الرئيسي من القائمة:",
            reply_markup=keyboard
        )

    # اختيار موضوع فرعي
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
        msg_text = "أدخل عدد الأسئلة المطلوبة (أرسل رقمًا فقط):"
        sent_msg = await query.message.edit_text(
            text=msg_text,
            reply_markup=kb
        )
        context.user_data["ask_msg_id"] = sent_msg.message_id

    # زر الرجوع لقائمة المواضيع الفرعية
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
# 11) هاندلر للرسائل النصية (لعدد الأسئلة)
# -------------------------------------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # في المجموعات: عند كتابة إحدى العبارات "بوت سوي اسئلة" أو "بوت الاسئلة" أو "بوت وينك"
    if update.message.chat.type in ("group", "supergroup"):
        text_lower = update.message.text.lower()
        triggers = ["بوت سوي اسئلة", "بوت الاسئلة", "بوت وينك"]
        if any(trig in text_lower for trig in triggers):
            await start_command(update, context)
            return

    user_state = context.user_data.get(CURRENT_STATE_KEY, None)
    if user_state == STATE_ASK_NUM_QUESTIONS:
        # في المجموعات يجب الرد على رسالة البوت نفسها
        if update.message.chat.type in ("group", "supergroup"):
            if not update.message.reply_to_message or update.message.reply_to_message.from_user.id != context.bot.id:
                return

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
        chat_id = update.message.chat_id
        chat_type = update.message.chat.type

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

        context.chat_data[ACTIVE_QUIZ_KEY] = {
            "poll_ids": poll_ids,
            "poll_correct_answers": poll_correct_answers,
            "total": num_q,
            "participants": {},
            "chat_type": chat_type,
            "chat_id": chat_id
        }
        context.user_data[CURRENT_STATE_KEY] = None

# -------------------------------------------------
# 12) هاندلر لاستقبال إجابات المستخدم (PollAnswerHandler)
# -------------------------------------------------
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_options = poll_answer.option_ids

    quiz_data = context.chat_data.get(ACTIVE_QUIZ_KEY)
    if not quiz_data:
        return

    if poll_id not in quiz_data["poll_ids"]:
        return

    participant = quiz_data["participants"].get(user_id, {
        "answered_count": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "first_name": poll_answer.user.first_name
    })

    if len(selected_options) == 1:
        chosen_index = selected_options[0]
        correct_option_id = quiz_data["poll_correct_answers"][poll_id]

        participant["answered_count"] += 1
        if chosen_index == correct_option_id:
            participant["correct_count"] += 1
        else:
            participant["wrong_count"] += 1

        quiz_data["participants"][user_id] = participant

        # إذا أكمل المشارك جميع الأسئلة يتم إرسال النتيجة فوراً
        if participant["answered_count"] == quiz_data["total"]:
            correct = participant["correct_count"]
            wrong = participant["wrong_count"]
            total = quiz_data["total"]
            user_mention = f'<a href="tg://user?id={user_id}">{poll_answer.user.first_name}</a>'
            msg = (
                f"تم الانتهاء من الإجابة على {total} سؤال بواسطة {user_mention}.\n"
                f"الإجابات الصحيحة: {correct}\n"
                f"الإجابات الخاطئة: {wrong}\n"
                f"النتيجة النهائية: {correct} / {total}\n"
            )
            # محاولة إرسال النتيجة في الخاص، وإن فشل إرسالها في الدردشة العامة
            if quiz_data.get("chat_type") in ("group", "supergroup"):
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=msg,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Error sending private message: {e}")
                    await context.bot.send_message(
                        chat_id=quiz_data.get("chat_id", update.effective_chat.id),
                        text=msg,
                        parse_mode="HTML"
                    )
            else:
                await context.bot.send_message(
                    chat_id=quiz_data.get("chat_id", update.effective_chat.id),
                    text=msg,
                    parse_mode="HTML"
                )

# -------------------------------------------------
# 13) دالة main لتشغيل البوت
# -------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("medsums", medsums_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(PollAnswerHandler(poll_answer_handler))

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
