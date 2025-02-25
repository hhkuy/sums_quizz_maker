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
    Poll,
    InlineKeyboardMarkup
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
# 2) توكن البوت
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
    try:
        response = requests.get(TOPICS_JSON_URL)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching topics: {e}")
        return []

def fetch_questions(file_path: str):
    url = f"{BASE_RAW_URL}/{file_path}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching questions from {url}: {e}")
        return []

# -------------------------------------------------
# 5) مفاتيح لحفظ الحالة
# -------------------------------------------------
TOPICS_KEY = "topics"
CUR_TOPIC_IDX_KEY = "current_topic_index"
CUR_SUBTOPIC_IDX_KEY = "current_subtopic_index"
NUM_QUESTIONS_KEY = "num_questions"
CURRENT_STATE_KEY = "current_state"
QUESTIONS_KEY = "questions_list"
BATCH_SIZE = 50  # عدد الأسئلة في كل دفعة

# حالات البوت
STATE_SELECT_TOPIC = "select_topic"
STATE_SELECT_SUBTOPIC = "select_subtopic"
STATE_ASK_NUM_QUESTIONS = "ask_num_questions"
STATE_SENDING_QUESTIONS = "sending_questions"
STATE_WAITING_REPLY = "waiting_reply"

# -------------------------------------------------
# 6) دوال لإنشاء الأزرار
# -------------------------------------------------
def generate_topics_keyboard(topics_data):
    keyboard = []
    for i, topic in enumerate(topics_data):
        btn = InlineKeyboardButton(
            text=topic["topicName"],
            callback_data=f"topic_{i}"
        )
        keyboard.append([btn])
    return InlineKeyboardMarkup(keyboard)

def generate_subtopics_keyboard(topic, topic_index):
    keyboard = []
    subtopics = topic.get("subTopics", [])
    for j, sub in enumerate(subtopics):
        # جلب عدد الأسئلة لكل موضوع فرعي
        questions = fetch_questions(sub["file"])
        count = len(questions) if questions else 0
        btn_text = f"{sub['name']} ({count} سؤال)"
        btn = InlineKeyboardButton(
            text=btn_text,
            callback_data=f"subtopic_{topic_index}_{j}"
        )
        keyboard.append([btn])
    
    back_btn = InlineKeyboardButton("« رجوع", callback_data="go_back_topics")
    keyboard.append([back_btn])
    return InlineKeyboardMarkup(keyboard)

def generate_subtopic_options():
    keyboard = [
        [InlineKeyboardButton("إرسال جميع الأسئلة 🚀", callback_data="send_all")],
        [InlineKeyboardButton("اختيار عدد الأسئلة 🎯", callback_data="choose_num")],
        [InlineKeyboardButton("« رجوع", callback_data="go_back_subtopics")]
    ]
    return InlineKeyboardMarkup(keyboard)

def generate_batch_keyboard(remaining):
    keyboard = [
        [InlineKeyboardButton("إرسال الدفعة التالية ⏩", callback_data=f"next_batch_{remaining}")]
    ]
    return InlineKeyboardMarkup(keyboard)

# -------------------------------------------------
# 7) معالجات الأوامر
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topics_data = fetch_topics()
    context.user_data[TOPICS_KEY] = topics_data

    if not topics_data:
        await update.message.reply_text("حدث خطأ في جلب المواضيع!")
        return

    context.user_data[CURRENT_STATE_KEY] = STATE_SELECT_TOPIC
    keyboard = generate_topics_keyboard(topics_data)
    await update.message.reply_text("اختر الموضوع:", reply_markup=keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "الأوامر المتاحة:\n"
        "/start - بدء اختيار المواضيع\n"
        "/help - عرض المساعدة\n"
        "يمكنك مناداتي في المجموعات بـ: بوت وينك، بوت الأسئلة"
    )
    await update.message.reply_text(help_text)

# -------------------------------------------------
# 8) معالجات الكالباك
# -------------------------------------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("topic_"):
        topic_idx = int(data.split("_")[1])
        context.user_data[CUR_TOPIC_IDX_KEY] = topic_idx
        topics_data = context.user_data[TOPICS_KEY]
        chosen_topic = topics_data[topic_idx]
        
        keyboard = generate_subtopics_keyboard(chosen_topic, topic_idx)
        await query.message.edit_text(
            f"اختر الموضوع الفرعي لـ {chosen_topic['topicName']}:",
            reply_markup=keyboard
        )

    elif data.startswith("subtopic_"):
        _, t_idx, s_idx = data.split("_")
        context.user_data[CUR_TOPIC_IDX_KEY] = int(t_idx)
        context.user_data[CUR_SUBTOPIC_IDX_KEY] = int(s_idx)
        
        # عرض خيارات الموضوع الفرعي
        keyboard = generate_subtopic_options()
        await query.message.edit_text(
            "اختر طريقة الإرسال:",
            reply_markup=keyboard
        )

    elif data == "send_all":
        await handle_send_all(query, context)

    elif data == "choose_num":
        await query.message.edit_text(
            "قم بالرد على هذه الرسالة برقم عدد الأسئلة المطلوبة:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« رجوع", callback_data="go_back_options")]])
        )
        context.user_data[CURRENT_STATE_KEY] = STATE_WAITING_REPLY

    elif data.startswith("next_batch_"):
        remaining = int(data.split("_")[2])
        await send_questions_batch(context, query.message.chat_id, remaining)

    elif data == "go_back_topics":
        topics_data = context.user_data[TOPICS_KEY]
        keyboard = generate_topics_keyboard(topics_data)
        await query.message.edit_text("اختر الموضوع:", reply_markup=keyboard)

    elif data == "go_back_subtopics"):
        topic_idx = context.user_data[CUR_TOPIC_IDX_KEY]
        topics_data = context.user_data[TOPICS_KEY]
        chosen_topic = topics_data[topic_idx]
        keyboard = generate_subtopics_keyboard(chosen_topic, topic_idx)
        await query.message.edit_text(
            f"اختر الموضوع الفرعي لـ {chosen_topic['topicName']}:",
            reply_markup=keyboard
        )

    elif data == "go_back_options"):
        keyboard = generate_subtopic_options()
        await query.message.edit_text("اختر طريقة الإرسال:", reply_markup=keyboard)

# -------------------------------------------------
# 9) دوال مساعدة
# -------------------------------------------------
async def handle_send_all(query, context):
    topic_idx = context.user_data[CUR_TOPIC_IDX_KEY]
    subtopic_idx = context.user_data[CUR_SUBTOPIC_IDX_KEY]
    topics_data = context.user_data[TOPICS_KEY]
    subtopic = topics_data[topic_idx]["subTopics"][subtopic_idx]
    
    questions = fetch_questions(subtopic["file"])
    if not questions:
        await query.message.reply_text("لا توجد أسئلة متاحة!")
        return
    
    # حفظ الأسئلة وتقسيمها
    context.user_data[QUESTIONS_KEY] = questions
    await send_questions_batch(context, query.message.chat_id, len(questions))

async def send_questions_batch(context, chat_id, remaining):
    questions = context.user_data.get(QUESTIONS_KEY, [])
    start_idx = len(questions) - remaining
    batch = questions[start_idx:start_idx+BATCH_SIZE]
    remaining -= len(batch)
    
    # إرسال الدفعة
    for q in batch:
        await send_question(context, chat_id, q)
        await asyncio.sleep(0.5)
    
    if remaining > 0:
        keyboard = generate_batch_keyboard(remaining)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"تبقى {remaining} أسئلة، هل تريد إرسال الدفعة التالية؟",
            reply_markup=keyboard
        )
    else:
        await context.bot.send_message(chat_id=chat_id, text="تم إرسال جميع الأسئلة ✅")
        context.user_data.pop(QUESTIONS_KEY, None)

async def send_question(context, chat_id, question):
    clean_question = re.sub(r"<.*?>", "", question["question"]).strip()
    options = question["options"]
    correct_id = question["answer"]
    explanation = question.get("explanation", "")
    
    await context.bot.send_poll(
        chat_id=chat_id,
        question=clean_question,
        options=options,
        type=Poll.QUIZ,
        correct_option_id=correct_id,
        explanation=explanation,
        is_anonymous=False
    )

# -------------------------------------------------
# 10) معالجة الرسائل النصية
# -------------------------------------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # التحقق من الرد على رسالة البوت
    if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
        if context.user_data.get(CURRENT_STATE_KEY) == STATE_WAITING_REPLY:
            num = update.message.text.strip()
            if not num.isdigit():
                await update.message.reply_text("يرجى إدخال رقم صحيح!")
                return
            
            num = int(num)
            topic_idx = context.user_data[CUR_TOPIC_IDX_KEY]
            subtopic_idx = context.user_data[CUR_SUBTOPIC_IDX_KEY]
            topics_data = context.user_data[TOPICS_KEY]
            subtopic = topics_data[topic_idx]["subTopics"][subtopic_idx]
            
            questions = fetch_questions(subtopic["file"])
            if num > len(questions):
                await update.message.reply_text(f"الحد الأقصى هو {len(questions)} أسئلة!")
                return
            
            selected = random.sample(questions, num)
            context.user_data[QUESTIONS_KEY] = selected
            await send_questions_batch(context, update.message.chat_id, num)
            context.user_data[CURRENT_STATE_KEY] = None

    # معالجة المنادات في المجموعات
    elif update.message.chat.type in ("group", "supergroup"):
        text = update.message.text.lower()
        triggers = ["بوت وينك", "بوت الأسئلة", "بوت سوي اسئلة"]
        if any(t in text for t in triggers):
            await start_command(update, context)

# -------------------------------------------------
# 11) معالجة إجابات الاستفتاءات
# -------------------------------------------------
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    user_id = answer.user.id
    poll_id = answer.poll_id
    selected = answer.option_ids[0] if answer.option_ids else None
    
    # البحث عن السؤال في البيانات المؤقتة
    for quiz in context.chat_data.get("active_quizzes", []):
        if poll_id in quiz["poll_ids"]:
            if str(user_id) not in quiz["answers"]:
                quiz["answers"][str(user_id)] = {
                    "correct": 0,
                    "total": len(quiz["poll_ids"])
                }
            
            if selected == quiz["correct_answers"][poll_id]:
                quiz["answers"][str(user_id)]["correct"] += 1
            
            # إرسال النتيجة الفورية
            correct = quiz["answers"][str(user_id)]["correct"]
            total = quiz["answers"][str(user_id)]["total"]
            await context.bot.send_message(
                chat_id=quiz["chat_id"],
                text=f"@{answer.user.username} نتيجتك الحالية: {correct}/{total}"
            )
            
            # حذف الكويز عند الانتهاء
            if len(quiz["answers"][str(user_id)]) == quiz["total"]:
                context.chat_data["active_quizzes"].remove(quiz)

# -------------------------------------------------
# 12) تشغيل البوت
# -------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # إضافة المعالجات
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(PollAnswerHandler(poll_answer_handler))
    
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
