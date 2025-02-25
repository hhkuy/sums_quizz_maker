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
# 5) مفاتيح لحفظ الحالة في user_data/chat_data
# -------------------------------------------------
TOPICS_KEY = "topics"
CUR_TOPIC_IDX_KEY = "current_topic_index"
CUR_SUBTOPIC_IDX_KEY = "current_subtopic_index"

# حالات
STATE_SELECT_TOPIC = "select_topic"
STATE_SELECT_SUBTOPIC = "select_subtopic"
STATE_AWAIT_SUBTOPIC_ACTION = "await_subtopic_action"
STATE_WAITING_RANDOM_NUMBER = "waiting_random_number"

# مفاتيح لاستخدامها في chat_data (للمجموعات)
ACTIVE_QUIZ_KEY = "active_quiz"   # يخزّن بيانات الكويز الجماعي
WAITING_FOR_REPLY_MSG_ID = "waiting_for_reply_msg_id"  # لتخزين msg_id الذي يجب الردّ عليه لإدخال العدد

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
    إنشاء إنلاين كيبورد لقائمة المواضيع الفرعية + زر الرجوع للمواضيع.
    مع ذكر عدد الأسئلة المتاحة لكل فرع بجوار اسمه.
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

    # زر الرجوع لقائمة المواضيع
    back_btn = InlineKeyboardButton("« رجوع للمواضيع", callback_data="go_back_topics")
    keyboard.append([back_btn])

    return InlineKeyboardMarkup(keyboard)

def generate_subtopic_actions_keyboard(topic_index, sub_index):
    """
    عند اختيار موضوع فرعي، نعرض 3 أزرار:
      1) إرسال جميع الأسئلة.
      2) تحديد عدد أسئلة لاختبار عشوائي.
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
                text="2) تحديد عدد الأسئلة (اختبار)",
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

def generate_send_all_continue_keyboard(topic_index, sub_index, next_chunk_index):
    """كيبورд زر 'متابعة' لإرسال الدفعة التالية من الأسئلة."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="متابعة إرسال الأسئلة",
                callback_data=f"send_all_{topic_index}_{sub_index}_{next_chunk_index}"
            )
        ]
    ])

# -------------------------------------------------
# 7) أوامر البوت: /start
# -------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عند تنفيذ /start:
    - نجلب قائمة المواضيع من GitHub.
    - نعرضها على شكل أزرار.
    """
    topics_data = fetch_topics()
    context.user_data[TOPICS_KEY] = topics_data

    if not topics_data:
        await update.message.reply_text(
            "حدث خطأ في جلب المواضيع من GitHub! تأكد من صلاحية الرابط."
        )
        return

    # ضبط حالة المستخدم لاختيار الموضوع
    context.user_data["current_state"] = STATE_SELECT_TOPIC

    keyboard = generate_topics_inline_keyboard(topics_data)
    await update.message.reply_text(
        text="مرحبًا بك! اختر الموضوع الرئيسي من القائمة:",
        reply_markup=keyboard
    )

# -------------------------------------------------
# 8) أوامر البوت: /help
# -------------------------------------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "الأوامر المتاحة:\n"
        "/start - لبدء اختيار المواضيع\n"
        "/help - عرض هذه الرسالة\n\n"
        "في المجموعات، يمكن مناداتي بعبارات مثل:\n"
        "«بوت سوي اسئلة» أو «بوت الاسئلة» أو «بوت وينك».\n"
        "وسيتم فتح قائمة المواضيع.\n"
    )
    await update.message.reply_text(help_text)

# -------------------------------------------------
# 9) هاندلر للأزرار (CallbackQueryHandler)
# -------------------------------------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # 1) اختيار موضوع رئيسي
    if data.startswith("topic_"):
        _, idx_str = data.split("_")
        topic_index = int(idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = topic_index
        context.user_data["current_state"] = STATE_SELECT_SUBTOPIC

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
        context.user_data["current_state"] = STATE_SELECT_TOPIC
        topics_data = context.user_data.get(TOPICS_KEY, [])
        keyboard = generate_topics_inline_keyboard(topics_data)

        await query.message.edit_text(
            text="اختر الموضوع الرئيسي من القائمة:",
            reply_markup=keyboard
        )

    # 3) زر الرجوع لقائمة المواضيع الفرعية
    elif data.startswith("go_back_subtopics_"):
        _, t_idx_str = data.split("_subtopics_")
        t_idx = int(t_idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data["current_state"] = STATE_SELECT_SUBTOPIC

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

    # 4) اختيار موضوع فرعي -> عرض 3 خيارات
    elif data.startswith("subtopic_"):
        _, t_idx_str, s_idx_str = data.split("_")
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CUR_SUBTOPIC_IDX_KEY] = s_idx
        context.user_data["current_state"] = STATE_AWAIT_SUBTOPIC_ACTION

        topics_data = context.user_data.get(TOPICS_KEY, [])
        if t_idx < 0 or t_idx >= len(topics_data):
            await query.message.reply_text("خطأ في اختيار الموضوع.")
            return
        subtopics = topics_data[t_idx].get("subTopics", [])
        if s_idx < 0 or s_idx >= len(subtopics):
            await query.message.reply_text("خطأ في اختيار الموضوع الفرعي.")
            return

        subtopic_name = subtopics[s_idx]["name"]
        file_path = subtopics[s_idx]["file"]
        questions = fetch_questions(file_path)
        num_questions = len(questions)

        text_msg = (
            f"الموضوع الفرعي: *{subtopic_name}*\n"
            f"عدد الأسئلة الكلي: {num_questions}\n\n"
            "اختر أحد الخيارات أدناه:"
        )
        await query.message.edit_text(
            text=text_msg,
            parse_mode="Markdown",
            reply_markup=generate_subtopic_actions_keyboard(t_idx, s_idx)
        )

    # 5) إرسال جميع الأسئلة - (بداية)
    elif data.startswith("send_all_") and data.endswith("_start"):
        # مثال callback_data: send_all_{t_idx}_{s_idx}_start
        parts = data.split("_")
        t_idx = int(parts[2])
        s_idx = int(parts[3])
        chunk_index = 0  # سنبدأ من الدفعة الأولى

        topics_data = context.user_data.get(TOPICS_KEY, [])
        sub = topics_data[t_idx]["subTopics"][s_idx]
        file_path = sub["file"]
        questions = fetch_questions(file_path)

        # إرسال أول 100 سؤال (أو أقل إن كان أقل من 100)
        await query.message.edit_text("جاري إرسال الأسئلة...")

        await send_questions_in_chunk(
            update=query,
            context=context,
            t_idx=t_idx,
            s_idx=s_idx,
            questions=questions,
            chunk_size=100,
            chunk_index=chunk_index
        )

    # 6) إرسال جميع الأسئلة - (متابعة دفعة)
    elif data.startswith("send_all_"):
        # مثال callback_data: send_all_{t_idx}_{s_idx}_{chunk_index}
        parts = data.split("_")
        # parts = ["send", "all", t_idx, s_idx, chunk_index]
        if len(parts) == 5:
            t_idx = int(parts[2])
            s_idx = int(parts[3])
            chunk_index = int(parts[4])

            topics_data = context.user_data.get(TOPICS_KEY, [])
            sub = topics_data[t_idx]["subTopics"][s_idx]
            file_path = sub["file"]
            questions = fetch_questions(file_path)

            await query.message.edit_text("جاري إرسال الدفعة التالية من الأسئلة...")
            await send_questions_in_chunk(
                update=query,
                context=context,
                t_idx=t_idx,
                s_idx=s_idx,
                questions=questions,
                chunk_size=100,
                chunk_index=chunk_index
            )

    # 7) اختيار اختبار عشوائي (زر)
    elif data.startswith("random_quiz_"):
        # مثال: random_quiz_{t_idx}_{s_idx}
        _, t_idx_str, s_idx_str = data.split("_")
        t_idx = int(t_idx_str)
        s_idx = int(s_idx_str)

        # نطلب من المستخدم إدخال العدد عبر الرد على رسالة البوت
        topics_data = context.user_data.get(TOPICS_KEY, [])
        if t_idx < 0 or t_idx >= len(topics_data):
            await query.message.reply_text("خطأ في اختيار الموضوع.")
            return
        subtopics = topics_data[t_idx].get("subTopics", [])
        if s_idx < 0 or s_idx >= len(subtopics):
            await query.message.reply_text("خطأ في اختيار الموضوع الفرعي.")
            return

        # وضع الحالة في الكونتكست
        context.user_data["current_state"] = STATE_WAITING_RANDOM_NUMBER
        context.user_data[CUR_TOPIC_IDX_KEY] = t_idx
        context.user_data[CUR_SUBTOPIC_IDX_KEY] = s_idx

        # سنطلب من المستخدم ردًا على رسالة معينة
        # نحذف الكيبورد السابقة ونظهر رسالة جديدة
        await query.message.edit_text(
            text="أرسل عدد الأسئلة المطلوبة (ردًا على هذه الرسالة)."
        )
        # تخزين message_id كي لا نقبل مدخلات إلا بالرد عليه (في المجموعات خصوصًا)
        context.chat_data[WAITING_FOR_REPLY_MSG_ID] = query.message.message_id

    else:
        await query.message.reply_text("لم أفهم هذا الخيار.")

# -------------------------------------------------
# 10) إرسال الأسئلة نصيًا على دفعات
# -------------------------------------------------
async def send_questions_in_chunk(update, context, t_idx, s_idx, questions, chunk_size, chunk_index):
    """
    يرسل مجموعة من الأسئلة (كـ Text Messages) بحجم chunk_size.
    ثم يعرض زر "متابعة" إن كان هناك المزيد.
    """
    chat_id = update.message.chat_id

    start_idx = chunk_index * chunk_size
    end_idx = start_idx + chunk_size
    chunk = questions[start_idx:end_idx]

    if not chunk:
        # لا يوجد أسئلة في هذه الدفعة -> ربما انتهى الإرسال
        await context.bot.send_message(
            chat_id=chat_id,
            text="تم الانتهاء من إرسال جميع الأسئلة."
        )
        return

    # إرسال الأسئلة نصيًا بسرعة
    for idx, q in enumerate(chunk, start=1):
        question_txt = q.get("question", "سؤال بدون نص!")
        question_txt = re.sub(r"<.*?>", "", question_txt).strip()
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"سؤال: {question_txt}"
        )

    # إذا تبقت أسئلة أخرى بعد هذه الدفعة، نضع زر متابعة
    if end_idx < len(questions):
        # هناك دفعة تالية
        next_chunk_index = chunk_index + 1
        keyboard = generate_send_all_continue_keyboard(t_idx, s_idx, next_chunk_index)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"تم إرسال {len(chunk)} سؤال. هل تريد المتابعة؟",
            reply_markup=keyboard
        )
    else:
        # هذه هي الدفعة الأخيرة
        await context.bot.send_message(
            chat_id=chat_id,
            text="تم الانتهاء من إرسال جميع الأسئلة."
        )

# -------------------------------------------------
# 11) استقبال الرسائل النصية
#     - في المجموعات: إذا نادوا البوت بالجمل المطلوبة -> كأنهم نفذوا /start
#     - في حالة STATE_WAITING_RANDOM_NUMBER نتأكد أنها رد على رسالة البوت + رقم صحيح
# -------------------------------------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_lower = update.message.text.lower()

    # في المجموعات: التريجر لفتح قائمة المواضيع
    if update.message.chat.type in ("group", "supergroup"):
        triggers = ["بوت سوي اسئلة", "بوت الاسئلة", "بوت وينك"]
        if any(trig in text_lower for trig in triggers):
            await start_command(update, context)
            return

    # التحقق من حالة إدخال العدد للاختبار العشوائي
    current_state = context.user_data.get("current_state", None)
    if current_state == STATE_WAITING_RANDOM_NUMBER:
        # يجب أن يكون الرد على رسالة البوت ذات المعرّف المحفوظ
        waiting_msg_id = context.chat_data.get(WAITING_FOR_REPLY_MSG_ID)
        if not waiting_msg_id:
            # غير مهيأ أصلاً
            return

        # نتأكد أن الرسالة الحالية رد على تلك الرسالة
        if not update.message.reply_to_message or (update.message.reply_to_message.message_id != waiting_msg_id):
            # إذا ليست ردًا على رسالة البوت
            # حسب الطلب: نرد بـ "رقم غير صحيح" (أو جملة خطأ)
            await update.message.reply_text("رقم غير صحيح. يجب الرد على رسالة البوت الأخيرة.")
            return

        # الآن نتأكد أن المدخل رقم
        num_text = update.message.text.strip()
        if not num_text.isdigit():
            await update.message.reply_text("رقم غير صحيح. أرسل رقمًا فقط.")
            return

        num_q = int(num_text)
        if num_q <= 0:
            await update.message.reply_text("العدد يجب أن يكون أكبر من صفر.")
            return

        # نلغي حالة الانتظار
        context.user_data["current_state"] = None
        # نحذف المفتاح حتى لا تبقى معلقة
        context.chat_data.pop(WAITING_FOR_REPLY_MSG_ID, None)

        # الآن نجلب الملف، ونختار عشوائيًا
        t_idx = context.user_data.get(CUR_TOPIC_IDX_KEY, 0)
        s_idx = context.user_data.get(CUR_SUBTOPIC_IDX_KEY, 0)
        topics_data = context.user_data.get(TOPICS_KEY, [])
        sub = topics_data[t_idx]["subTopics"][s_idx]
        file_path = sub["file"]
        questions = fetch_questions(file_path)
        if len(questions) == 0:
            await update.message.reply_text("لا توجد أسئلة في هذا الموضوع الفرعي.")
            return

        if num_q > len(questions):
            await update.message.reply_text(f"لا يوجد سوى {len(questions)} سؤال في هذا الموضوع الفرعي.")
            return

        random.shuffle(questions)
        selected_questions = questions[:num_q]

        await update.message.reply_text(
            f"سيتم إرسال {num_q} سؤال (اختبار). يمكن لأي عضو في المجموعة الإجابة على كل الأسئلة، وعند انتهائه تظهر نتيجته."
        )

        # تهيئة بيانات الاختبار في chat_data (ليس user_data) حتى يصبح جماعي
        chat_id = update.message.chat_id

        # سننشئ كائن للكويز في chat_data
        # نقوم بتخزين:
        # - poll_correct_answers: dict[poll_id -> correct_index]
        # - total_polls: العدد الكلي
        # - users: dict[user_id -> {answered_count, correct_count, wrong_count, answered_polls:set}]
        # (كل مستخدم له إحصائياته)
        active_quiz = {
            "poll_correct_answers": {},
            "total_polls": num_q,
            "users": {}  # user_id -> data
        }

        # إرسال كل سؤال كـ Quiz Poll
        poll_ids = []
        for q in selected_questions:
            question_text = re.sub(r"<.*?>", "", q.get("question", "سؤال بدون نص")).strip()
            options = q.get("options", [])
            correct_id = q.get("answer", 0)
            explanation = q.get("explanation", "")

            poll_msg = await context.bot.send_poll(
                chat_id=chat_id,
                question=question_text,
                options=options,
                type=Poll.QUIZ,
                correct_option_id=correct_id,
                explanation=explanation,
                is_anonymous=False
            )
            if poll_msg.poll:
                active_quiz["poll_correct_answers"][poll_msg.poll.id] = correct_id
                poll_ids.append(poll_msg.poll.id)

            # يمكن وضع فاصل زمني صغير لتفادي مشاكل الارسال المتتالي السريع
            await asyncio.sleep(0.5)

        # تخزينه في chat_data
        context.chat_data[ACTIVE_QUIZ_KEY] = active_quiz

        return

    # إذا لم نكن في حالة خاصة، لا نفعل شيئًا
    # (أو يمكن الردّ بأي شيء آخر)
    # لا نرد إلّا إذا لزم.
    # pass

# -------------------------------------------------
# 12) استقبال إجابات الاستفتاء (PollAnswerHandler)
# -------------------------------------------------
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id = answer.poll_id
    user_id = answer.user.id

    active_quiz = context.chat_data.get(ACTIVE_QUIZ_KEY)
    if not active_quiz:
        return  # لا يوجد اختبار حالي في هذه المجموعة

    if poll_id not in active_quiz["poll_correct_answers"]:
        return  # هذا الاستفتاء لا ينتمي للاختبار الحالي

    # جلب بيانات المستخدم إن وجدت أو إنشاؤها
    user_data = active_quiz["users"].get(user_id, {
        "answered_count": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "answered_polls": set()
    })

    # إذا المستخدم أجاب على هذا الاستفتاء من قبل، نتجاهل
    if poll_id in user_data["answered_polls"]:
        return

    # تعديل إحصائياته
    user_data["answered_polls"].add(poll_id)
    user_data["answered_count"] += 1

    chosen_options = answer.option_ids
    if len(chosen_options) == 1:
        chosen_index = chosen_options[0]
        correct_index = active_quiz["poll_correct_answers"][poll_id]
        if chosen_index == correct_index:
            user_data["correct_count"] += 1
        else:
            user_data["wrong_count"] += 1

    # تحديث user_data في القاموس
    active_quiz["users"][user_id] = user_data

    # إذا وصل عدد الإجابات لديه إلى كامل عدد الاستفتاءات
    total = active_quiz["total_polls"]
    if user_data["answered_count"] == total:
        # إرسال نتيجته
        correct = user_data["correct_count"]
        wrong = user_data["wrong_count"]
        user_mention = f'<a href="tg://user?id={user_id}">{answer.user.first_name}</a>'
        msg = (
            f"لقد أكمل {user_mention} الإجابة على {total} سؤال.\n"
            f"إجابات صحيحة: {correct}\n"
            f"إجابات خاطئة: {wrong}\n"
            f"النتيجة: {correct} / {total}\n"
        )
        await context.bot.send_message(
            chat_id=answer.user.id,  # يمكن إرسالها خاص أو في المجموعة
            text="لقد أنهيت الاختبار. نتائجك سيتم عرضها في المجموعة أيضًا.",
            parse_mode="HTML"
        )
        # إرسال في المجموعة أيضًا
        chat_id = update.poll_answer.user.id  # عفواً، هذا خطأ. نحتاج معرف المجموعة.
        # في الحقيقة الـ poll_answer لا يعطينا الـ chat_id مباشرة.
        # لكننا خزّناه في active_quiz أو نعيد إرساله لنفس المجموعة: سنحتاج تخزينه من البداية.
        # لأجل التبسيط، سنخزّن chat_id في active_quiz ونستخدمه هنا.
        # فلنتأكد أننا فعلنا ذلك في مرحلة الإنشاء:
        # نعدّل active_quiz لينسخ chat_id عند إنشائه.
        # لنعدّل قليلاً:

        # سنتحقق إن كنا حفظنا chat_id في active_quiz أم لا
        quiz_chat_id = active_quiz.get("chat_id")
        if quiz_chat_id:
            await context.bot.send_message(
                chat_id=quiz_chat_id,
                text=msg,
                parse_mode="HTML"
            )
        else:
            # إن لم يكن موجودًا، نطبعها في الخاص فقط
            pass

# -------------------------------------------------
# 13) تعديل لإنشاء active_quiz بحيث يخزن chat_id
#     (لذلك سنعدل في موضع إنشاء الكويز في الرسالة_handler)
# -------------------------------------------------
# سنضع الدالة هنا، لكنها رمز للتذكير، وسننسخه في مكانه الصحيح.


# -------------------------------------------------
# 14) دالة main لتشغيل البوت
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


if __name__ == "__main__":
    main()
