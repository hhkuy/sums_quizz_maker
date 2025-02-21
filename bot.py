import logging
import requests
import json
import random
import re
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PollAnswerHandler,
    filters
)

import google.generativeai as genai

# ---------------------------------------------
# تهيئة Gemini API
# ---------------------------------------------
GEMINI_API_KEY = 'AIzaSyBV1-O6c-1mjCPwBrlbVFpLlx0c8deDESA'
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')  # نموذج سريع ومُحسَّن

# ---------------------------------------------
# توكن البوت الموحد (تم استخدام توكن بوت الأسئلة)
# ---------------------------------------------
BOT_TOKEN = "7633072361:AAHnzREYTKKRFiTiq7HDZBalnwnmgivY8_I"

# ---------------------------------------------
# قائمة الرسائل التفاعلية (لبوت الذكاء الاصطناعي)
# ---------------------------------------------
INTERACTIVE_MESSAGES = [
    "انطي صبر جاي اكتب...",
    "خالي اصبرلي...",
    "راسك مربع انطي صبر...",
    "شوي شوي جاي...",
    "اصبر شوي ماكو تعب...",
    "جاري الكتابة، خذ راحتك..."
]

# ---------------------------------------------
# مفاتيح وحالة البوت الخاص بالأسئلة
# ---------------------------------------------
TOPICS_KEY = "topics"
CUR_TOPIC_IDX_KEY = "current_topic_index"
CUR_SUBTOPIC_IDX_KEY = "current_subtopic_index"
NUM_QUESTIONS_KEY = "num_questions"
CURRENT_STATE_KEY = "current_state"
ACTIVE_QUIZ_KEY = "active_quiz"

STATE_SELECT_TOPIC = "select_topic"
STATE_SELECT_SUBTOPIC = "select_subtopic"
STATE_ASK_NUM_QUESTIONS = "ask_num_questions"
STATE_SENDING_QUESTIONS = "sending_questions"

# ---------------------------------------------
# روابط GitHub لجلب بيانات الاختبارات
# ---------------------------------------------
BASE_RAW_URL = "https://raw.githubusercontent.com/hhkuy/Sums_Q/main"
TOPICS_JSON_URL = f"{BASE_RAW_URL}/data/topics.json"

def fetch_topics():
    """جلب ملف الـ topics.json من مستودع GitHub على شكل list[dict]."""
    try:
        response = requests.get(TOPICS_JSON_URL)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Error fetching topics: {e}")
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
        return response.json()
    except Exception as e:
        logging.error(f"Error fetching questions from {url}: {e}")
        return []

def generate_topics_inline_keyboard(topics_data):
    """
    إنشاء إنلاين كيبورد لقائمة المواضيع الرئيسية.
    """
    keyboard = []
    for i, topic in enumerate(topics_data):
        btn = InlineKeyboardButton(text=topic["topicName"], callback_data=f"topic_{i}")
        keyboard.append([btn])
    return InlineKeyboardMarkup(keyboard)

def generate_subtopics_inline_keyboard(topic, topic_index):
    """
    إنشاء إنلاين كيبورد لقائمة المواضيع الفرعية + زر الرجوع.
    """
    keyboard = []
    subtopics = topic.get("subTopics", [])
    for j, sub in enumerate(subtopics):
        btn = InlineKeyboardButton(text=sub["name"], callback_data=f"subtopic_{topic_index}_{j}")
        keyboard.append([btn])
    back_btn = InlineKeyboardButton("« رجوع للمواضيع", callback_data="go_back_topics")
    keyboard.append([back_btn])
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------
# أمر /start المدمج
# ---------------------------------------------
async def merged_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /start:
    - عرض قائمة الخيارات لاختيار بين بوت الأسئلة وبوت الذكاء الاصطناعي.
    """
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("بوت الأسئلة", callback_data="start_quiz")],
        [InlineKeyboardButton("بوت الذكاء الاصطناعي", callback_data="start_ai")]
    ])
    await update.effective_message.reply_text(
        "مرحبًا! اختر أحد الخيارات:",
        reply_markup=keyboard
    )

# ---------------------------------------------
# أمر /help
# ---------------------------------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "الأوامر المتاحة:\n"
        "/start - لبدء البوت واختيار وضع التشغيل\n"
        "/help - عرض هذه الرسالة\n\n"
        "يمكنك اختيار:\n"
        "1) بوت الأسئلة: لاختيار مواضيع واختبارات.\n"
        "2) بوت الذكاء الاصطناعي: للدردشة وطلب الشرح.\n"
        "مثال: إذا قمت بالرد على سؤال في الاختبار وكتبت 'اشرحلي هذا السؤال', سيقوم البوت بشرحه.\n"
        "في المجموعات، استخدم عبارات مثل 'بوت سوي اسئلة' أو 'بوت الاسئلة' أو 'بوت وينك' لبدء الاختبار."
    )
    await update.message.reply_text(help_text)

# ---------------------------------------------
# بدء بوت الأسئلة
# ---------------------------------------------
async def quiz_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topics_data = fetch_topics()
    context.user_data[TOPICS_KEY] = topics_data
    if not topics_data:
        await update.effective_message.reply_text("حدث خطأ في جلب المواضيع من GitHub! تأكد من صلاحية الرابط.")
        return
    context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC
    keyboard = generate_topics_inline_keyboard(topics_data)
    await update.effective_message.reply_text(
        text="اختر الموضوع الرئيسي من القائمة:",
        reply_markup=keyboard
    )
    # تحديد وضع التشغيل لبوت الأسئلة
    context.user_data["mode"] = "quiz"

# ---------------------------------------------
# هاندلر للأزرار (CallbackQueryHandler)
# ---------------------------------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "start_quiz":
        context.user_data["mode"] = "quiz"
        await quiz_start_command(update, context)
    elif data == "start_ai":
        context.user_data["mode"] = "ai"
        await query.message.edit_text("مرحبًا! أنا بوت ذكاء اصطناعي. كيف يمكنني مساعدتك؟")
    elif data.startswith("topic_"):
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

        back_btn = InlineKeyboardButton("« رجوع للمواضيع الفرعية", callback_data=f"go_back_subtopics_{t_idx}")
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

# ---------------------------------------------
# هاندلر للرسائل النصية الخاصة بعدد الأسئلة (بوت الأسئلة)
# ---------------------------------------------
async def quiz_number_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get(CURRENT_STATE_KEY) == STATE_ASK_NUM_QUESTIONS:
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
            await update.message.reply_text(f"الأسئلة غير كافية. العدد المتاح هو: {len(questions)}")
            return

        random.shuffle(questions)
        selected_questions = questions[:num_q]

        await update.message.reply_text(f"سيتم إرسال {num_q} سؤال(أسئلة) على شكل استفتاء (Quiz). بالتوفيق!")

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

# ---------------------------------------------
# هاندلر لاستقبال إجابات الاستفتاء (PollAnswerHandler)
# ---------------------------------------------
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

# ---------------------------------------------
# هاندلر لرسائل بوت الذكاء الاصطناعي (للدردشة أو الشرح)
# ---------------------------------------------
async def ai_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # إذا كانت الحالة تطلب إدخال رقم (في مرحلة الأسئلة) فلا نعالجها هنا
    if context.user_data.get(CURRENT_STATE_KEY) == STATE_ASK_NUM_QUESTIONS and text.isdigit():
        return

    mode = context.user_data.get("mode", "ai")
    # نعالج الرسالة إذا كان المستخدم في وضع بوت الذكاء الاصطناعي
    # أو إذا احتوت الرسالة على كلمة "اشرح" (مثلاً لشرح سؤال)
    if mode != "ai" and "اشرح" not in text:
        return

    await context.bot.send_chat_action(chat_id=update.message.chat_id, action="typing")
    interactive_message = random.choice(INTERACTIVE_MESSAGES)
    sent_message = await update.message.reply_text(interactive_message)

    try:
        response = await asyncio.to_thread(model.generate_content, text)
        await context.bot.edit_message_text(
            chat_id=update.message.chat_id,
            message_id=sent_message.message_id,
            text=response.text
        )
    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=update.message.chat_id,
            message_id=sent_message.message_id,
            text=f"حدث خطأ: {str(e)}"
        )

# ---------------------------------------------
# هاندلر لرسائل المجموعات لتفعيل بوت الأسئلة
# ---------------------------------------------
async def group_trigger_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type in ("group", "supergroup"):
        text_lower = update.message.text.lower()
        triggers = ["بوت سوي اسئلة", "بوت الاسئلة", "بوت وينك"]
        if any(trig in text_lower for trig in triggers):
            context.user_data["mode"] = "quiz"
            await quiz_start_command(update, context)

# ---------------------------------------------
# هاندلر للرسائل المعدلة (Edited Messages) لبوت الذكاء الاصطناعي
# ---------------------------------------------
async def edited_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.edited_message
    bot_user = await context.bot.get_me()
    if message.from_user.id == bot_user.id:
        await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")
        interactive_message = random.choice(INTERACTIVE_MESSAGES)
        sent_message = await message.reply_text(interactive_message)
        try:
            response = await asyncio.to_thread(model.generate_content, "لماذا قمت بحذف الرسالة؟")
            await context.bot.edit_message_text(
                chat_id=message.chat_id,
                message_id=sent_message.message_id,
                text=response.text
            )
        except Exception as e:
            await context.bot.edit_message_text(
                chat_id=message.chat_id,
                message_id=sent_message.message_id,
                text=f"حدث خطأ: {str(e)}"
            )

# ---------------------------------------------
# دالة main لتشغيل البوت
# ---------------------------------------------
def main():
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ربط الأوامر
    app.add_handler(CommandHandler("start", merged_start_command))
    app.add_handler(CommandHandler("help", help_command))

    # ربط الأزرار
    app.add_handler(CallbackQueryHandler(callback_handler))

    # ربط الرسائل الخاصة بالأسئلة (الرقم) والتريجر في المجموعات
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, quiz_number_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_trigger_handler))

    # ربط رسائل الدردشة/الشرح (بوت الذكاء الاصطناعي)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_message_handler))

    # ربط إجابات الاستفتاء
    app.add_handler(PollAnswerHandler(poll_answer_handler))

    # ربط الرسائل المعدلة
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, edited_message_handler))

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
