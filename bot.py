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

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
BOT_TOKEN = "7633072361:AAHnzREYTKKRFiTiq7HDZBalnwnmgivY8_I"
DATA_URL = "https://raw.githubusercontent.com/Dr-Mostafa-Gamal/exam_questions/main/topics.json"
TOPICS_KEY = "topics"
CUR_TOPIC_IDX_KEY = "current_topic_index"
CUR_SUBTOPIC_IDX_KEY = "current_subtopic_index"
NUM_QUESTIONS_KEY = "number_of_questions"
CURRENT_STATE_KEY = "current_state"
ACTIVE_QUIZ_KEY = "active_quiz"
STATE_ASK_NUM_QUESTIONS = "ask_number_of_questions"
STATE_SENDING_QUESTIONS = "sending_questions"

# Constants for pagination
QUESTIONS_PER_PAGE = 100
SEND_ALL_QUESTIONS_KEY = "send_all_questions"

# Helper function to fetch data from URL
def fetch_data(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching data: {e}")
        return None

# Helper function to fetch questions from a file
def fetch_questions(file_path):
    try:
        response = requests.get(file_path)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching questions from {file_path}: {e}")
        return []

# Function to generate the main topics keyboard
def generate_topics_inline_keyboard(topics):
    keyboard = []
    for i, topic in enumerate(topics):
        btn = InlineKeyboardButton(topic["name"], callback_data=f"topic_{i}")
        keyboard.append([btn])
    return InlineKeyboardMarkup(keyboard)

# Function to generate subtopics keyboard with question count
def generate_subtopics_inline_keyboard(topic, topic_index):
    keyboard = []
    subtopics = topic.get("subTopics", [])
    for j, sub in enumerate(subtopics):
        question_count = len(fetch_questions(sub["file"]))
        btn = InlineKeyboardButton(
            text=f"{sub['name']} ({question_count} أسئلة)",
            callback_data=f"subtopic_{topic_index}_{j}"
        )
        keyboard.append([btn])

    back_btn = InlineKeyboardButton("« رجوع للمواضيع", callback_data="go_back_topics")
    keyboard.append([back_btn])

    return InlineKeyboardMarkup(keyboard)

# Function to generate question options keyboard
def generate_question_options_keyboard(topic_index, subtopic_index):
    keyboard = [
        [InlineKeyboardButton("إرسال جميع الأسئلة", callback_data=f"send_all_{topic_index}_{subtopic_index}")],
        [InlineKeyboardButton("تحديد عدد الأسئلة", callback_data=f"select_num_{topic_index}_{subtopic_index}")],
        [InlineKeyboardButton("« رجوع", callback_data=f"go_back_subtopics_{topic_index}")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Command handler for /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topics_data = fetch_data(DATA_URL)

    if topics_data:
        context.user_data[TOPICS_KEY] = topics_data
        keyboard = generate_topics_inline_keyboard(topics_data)
        await update.message.reply_text("اختر موضوعًا:", reply_markup=keyboard)
    else:
        await update.message.reply_text("فشل في جلب البيانات. يرجى المحاولة لاحقًا.")

# Command handler for /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("هذا البوت يقدم أسئلة اختبارية. استخدم /start للبدء.")

# Callback handler for inline keyboards
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("topic_"):
        topic_index = int(data.split("_")[1])
        context.user_data[CUR_TOPIC_IDX_KEY] = topic_index
        topic = context.user_data[TOPICS_KEY][topic_index]
        keyboard = generate_subtopics_inline_keyboard(topic, topic_index)
        await query.message.edit_text(f"اختر موضوعًا فرعيًا من {topic['name']}:", reply_markup=keyboard)

    elif data == "go_back_topics":
        topics_data = context.user_data.get(TOPICS_KEY, [])
        keyboard = generate_topics_inline_keyboard(topics_data)
        await query.message.edit_text("اختر موضوعًا:", reply_markup=keyboard)

    elif data.startswith("go_back_subtopics_"):
        topic_index = int(data.split("_")[-1])
        topic = context.user_data[TOPICS_KEY][topic_index]
        keyboard = generate_subtopics_inline_keyboard(topic, topic_index)
        await query.message.edit_text(f"اختر موضوعًا فرعيًا من {topic['name']}:", reply_markup=keyboard)

    elif data.startswith("subtopic_"):
        _, t_idx_str, s_idx_str = data.split("_")
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CUR_SUBTOPIC_IDX_KEY] = s_idx

        keyboard = generate_question_options_keyboard(t_idx, s_idx)
        await query.message.edit_text(
            "اختر طريقة إرسال الأسئلة:",
            reply_markup=keyboard
        )

    elif data.startswith("send_all_"):
        _, t_idx_str, s_idx_str = data.split("_")
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)
        context.user_data[SEND_ALL_QUESTIONS_KEY] = True
        await send_paginated_questions(update, context, t_idx, s_idx)

    elif data.startswith("select_num_"):
        _, t_idx_str, s_idx_str = data.split("_")
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CUR_SUBTOPIC_IDX_KEY] = s_idx
        context.user_data[CURRENT_STATE_KEY] = STATE_ASK_NUM_QUESTIONS

        await query.message.edit_text(
            "أدخل عدد الأسئلة المطلوبة (أرسل رقمًا فقط):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« رجوع", callback_data=f"go_back_subtopics_{t_idx}")
            ]])
        )

# Function to send paginated questions
async def send_paginated_questions(update: Update, context: ContextTypes.DEFAULT_TYPE, topic_index, subtopic_index):
    topics_data = context.user_data.get(TOPICS_KEY, [])
    if topic_index < 0 or topic_index >= len(topics_data):
        await update.callback_query.message.edit_text("خطأ في اختيار الموضوع.")
        return

    subtopics = topics_data[topic_index].get("subTopics", [])
    if subtopic_index < 0 or subtopic_index >= len(subtopics):
        await update.callback_query.message.edit_text("خطأ في اختيار الموضوع الفرعي.")
        return

    file_path = subtopics[subtopic_index]["file"]
    all_questions = fetch_questions(file_path)
    
    if not all_questions:
        await update.callback_query.message.edit_text("لم أتمكن من جلب أسئلة لهذا الموضوع الفرعي.")
        return

    total_questions = len(all_questions)
    pages = (total_questions + QUESTIONS_PER_PAGE - 1) // QUESTIONS_PER_PAGE

    for page in range(pages):
        start_idx = page * QUESTIONS_PER_PAGE
        end_idx = min((page + 1) * QUESTIONS_PER_PAGE, total_questions)
        questions_chunk = all_questions[start_idx:end_idx]

        chunk_text = f"الأسئلة من {start_idx + 1} إلى {end_idx} (من أصل {total_questions}):\n\n"
        for idx, q in enumerate(questions_chunk, start=start_idx + 1):
            chunk_text += f"{idx}. {q['question']}\n"
            for option_idx, option in enumerate(q['options']):
                chunk_text += f"   {chr(97 + option_idx)}) {option}\n"
            chunk_text += f"الإجابة الصحيحة: {chr(97 + q['answer'])}\n\n"

        await update.callback_query.message.reply_text(chunk_text)
        await asyncio.sleep(1)  # To avoid flooding

    await update.callback_query.message.reply_text("تم إرسال جميع الأسئلة.")

# Message handler
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type in ("group", "supergroup"):
        if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
            # Process the message only if it's a reply to the bot's message
            await process_message(update, context)
        else:
            # Check for bot triggers
            text_lower = update.message.text.lower()
            triggers = ["بوت سوي اسئلة", "بوت الاسئلة", "بوت وينك"]
            if any(trig in text_lower for trig in triggers):
                await start_command(update, context)
    else:
        # In private chats, process all messages
        await process_message(update, context)

# Function to process messages
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_state = context.user_data.get(CURRENT_STATE_KEY, None)

    if user_state == STATE_ASK_NUM_QUESTIONS:
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

        # Fetch and send questions
        await send_quiz_questions(update, context)

# Function to send quiz questions
async def send_quiz_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topics_data = context.user_data.get(TOPICS_KEY, [])
    t_idx = context.user_data.get(CUR_TOPIC_IDX_KEY, 0)
    s_idx = context.user_data.get(CUR_SUBTOPIC_IDX_KEY, 0)
    num_q = context.user_data.get(NUM_QUESTIONS_KEY, 0)

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
        "answered_count": 0,
        "user_results": {}  # To store results for each user
    }

    context.user_data[CURRENT_STATE_KEY] = None

# Poll answer handler
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_options = poll_answer.option_ids

    quiz_data = context.user_data.get(ACTIVE_QUIZ_KEY)
    if not quiz_data or poll_id not in quiz_data["poll_ids"]:
        return

    if len(selected_options) == 1:
        chosen_index = selected_options[0]
        correct_option_id = quiz_data["poll_correct_answers"][poll_id]

        if user_id not in quiz_data["user_results"]:
            quiz_data["user_results"][user_id] = {
                "correct_count": 0,
                "wrong_count": 0,
                "answered_count": 0
            }

        user_result = quiz_data["user_results"][user_id]
        user_result["answered_count"] += 1
        if chosen_index == correct_option_id:
            user_result["correct_count"] += 1
        else:
            user_result["wrong_count"] += 1

        # Check if this user has answered all questions
        if user_result["answered_count"] == quiz_data["total"]:
            correct = user_result["correct_count"]
            wrong = user_result["wrong_count"]
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

        # Check if all users have completed the quiz
        if all(user["answered_count"] == quiz_data["total"] for user in quiz_data["user_results"].values()):
            # Quiz is complete, clear the data
            context.user_data[ACTIVE_QUIZ_KEY] = None

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))

    # Callback query handler
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Poll answer handler
    app.add_handler(PollAnswerHandler(poll_answer_handler))

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

