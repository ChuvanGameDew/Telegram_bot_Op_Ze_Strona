import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, \
    ReplyKeyboardRemove
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from supabase import create_client, Client

# ========== ДОБАВЛЯЕМ FLASK ДЛЯ RENDER ==========
from flask import Flask
from threading import Thread
import os

# Создаем маленькое веб-приложение
web_app = Flask(__name__)

@web_app.route('/')
@web_app.route('/health')
def health_check():
    return "", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port, debug=False)

web_thread = Thread(target=run_web_server)
web_thread.start()
# ========== КОНЕЦ БЛОКА ДЛЯ RENDER ==========

# ========== НАСТРОЙКИ ==========
TOKEN = "8644034235:AAGzJYsXf0E7OJyfShSK-KZadIUIGIEE26s"
SUPABASE_URL = "https://lkpqbskqtiiftdtqjbyp.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxrcHFic2txdGlpZnRkdHFqYnlwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ1NDg5ODIsImV4cCI6MjA5MDEyNDk4Mn0.vNADDb9v6cWPgEIJ5xkr8WkOi0DwlpL5kE-Snv9kaFY"

CHANNEL_USERNAME = "@andrey_trueself_channel"
CHANNEL_LINK = "https://t.me/andrey_trueself_channel"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


class Questionnaire(StatesGroup):
    question1 = State()
    question2 = State()
    question3 = State()
    question4 = State()
    question5 = State()
    question6 = State()
    ask_name = State()
    ask_age = State()
    ask_gender = State()
    ask_city = State()


# ========== ФУНКЦИЯ ПРОВЕРКИ ПОДПИСКИ ==========

async def check_subscription(user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return chat_member.status not in ['left', 'kicked']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False


# ========== ФУНКЦИИ РАБОТЫ С БАЗОЙ ==========

def get_or_create_user(tg_id: int, username: str, name: str):
    try:
        result = supabase.table("bot_users").select("*").eq("tg_id", tg_id).execute()
        if len(result.data) == 0:
            new_user = supabase.table("bot_users").insert({
                "tg_id": tg_id,
                "username": username or "нет username",
                "name": name or "нет имени",
                "completed_test": False,
                "is_subscribed": False
            }).execute()
            logger.info(f"✅ Создан новый пользователь: {tg_id}")
            return new_user.data[0]["id"], new_user.data[0]
        else:
            logger.info(f"👤 Найден существующий пользователь: {tg_id}")
            return result.data[0]["id"], result.data[0]
    except Exception as e:
        logger.error(f"❌ Ошибка в get_or_create_user: {e}")
        return None, None


def save_answer(user_id: int, question_number: int, answer: str):
    try:
        supabase.table("user_answers").insert({
            "user_id": user_id,
            "question_number": question_number,
            "answer": answer
        }).execute()
        logger.info(f"💾 Сохранён ответ {question_number} для user_id={user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения ответа: {e}")
        return False


def update_user_info(user_id: int, field: str, value: str):
    try:
        supabase.table("bot_users").update({
            field: value,
            "updated_at": datetime.now().isoformat()
        }).eq("id", user_id).execute()
        logger.info(f"✅ Обновлено {field}={value} для user_id={user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка обновления {field}: {e}")
        return False


def update_test_completed(user_id: int):
    try:
        supabase.table("bot_users").update({
            "completed_test": True,
            "updated_at": datetime.now().isoformat()
        }).eq("id", user_id).execute()
        logger.info(f"✅ Тест завершён для user_id={user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка обновления статуса: {e}")


def has_user_completed_test(tg_id: int) -> bool:
    try:
        result = supabase.table("bot_users").select("completed_test").eq("tg_id", tg_id).execute()
        if result.data and len(result.data) > 0:
            return result.data[0].get("completed_test", False)
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка проверки теста: {e}")
        return False


def save_user_message(tg_id: int, message_text: str):
    """Сохраняет сообщение от пользователя в таблицу user_messages (только если тест пройден)"""
    try:
        if not has_user_completed_test(tg_id):
            logger.info(f"⏳ Пользователь {tg_id} ещё не прошёл тест, сообщение не сохранено")
            return False
        
        result = supabase.table("bot_users").select("id").eq("tg_id", tg_id).execute()
        if result.data:
            db_user_id = result.data[0]["id"]
            supabase.table("user_messages").insert({
                "user_id": db_user_id,
                "message": message_text
            }).execute()
            logger.info(f"💾 Сохранено сообщение от пользователя {tg_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения сообщения пользователя: {e}")
        return False


# ========== MIDDLEWARE ДЛЯ СОХРАНЕНИЯ СООБЩЕНИЙ (НЕ БЛОКИРУЕТ ОБРАБОТКУ) ==========

@dp.message()
async def save_user_messages_middleware(message: types.Message, next_handler):
    """Сохраняет сообщения пользователя, но не блокирует их обработку"""
    tg_id = message.from_user.id
    
    # Сохраняем сообщение (только если тест пройден и это не команда)
    if message.text and not message.text.startswith('/'):
        save_user_message(tg_id, message.text)
    
    # Передаём сообщение дальше к другим обработчикам
    await next_handler()


# ========== ФУНКЦИЯ ОТПРАВКИ СООБЩЕНИЙ ИЗ ОЧЕРЕДИ ==========

async def process_message_queue():
    try:
        messages = supabase.table("admin_messages").select("*").eq("status", "pending").execute()
        if not messages.data:
            return
        logger.info(f"📨 Найдено {len(messages.data)} сообщений в очереди")
        for msg in messages.data:
            try:
                user_id = msg["user_id"]
                user_result = supabase.table("bot_users").select("tg_id, name, username").eq("id", user_id).execute()
                if not user_result.data:
                    supabase.table("admin_messages").update({
                        "status": "failed", "error": f"User {user_id} not found"
                    }).eq("id", msg["id"]).execute()
                    continue
                tg_id = user_result.data[0]["tg_id"]
                await bot.send_message(chat_id=tg_id, text=msg["message"])
                supabase.table("admin_messages").update({
                    "status": "sent", "sent_at": datetime.now().isoformat()
                }).eq("id", msg["id"]).execute()
                logger.info(f"✅ Отправлено сообщение {msg['id']} пользователю {tg_id}")
                await asyncio.sleep(1)
            except Exception as e:
                supabase.table("admin_messages").update({
                    "status": "failed", "error": str(e)
                }).eq("id", msg["id"]).execute()
                logger.error(f"❌ Ошибка отправки сообщения {msg['id']}: {e}")
    except Exception as e:
        logger.error(f"❌ Ошибка в process_message_queue: {e}")


async def message_queue_worker():
    while True:
        await process_message_queue()
        await asyncio.sleep(5)


async def check_all_subscriptions():
    try:
        users = supabase.table("bot_users").select("id, tg_id, is_subscribed").execute()
        if not users.data:
            return
        updated_count = 0
        for user in users.data:
            tg_id = user["tg_id"]
            current_status = user.get("is_subscribed", False)
            is_subscribed = await check_subscription(tg_id)
            if current_status != is_subscribed:
                supabase.table("bot_users").update({
                    "is_subscribed": is_subscribed,
                    "subscribed_at": datetime.now().isoformat() if is_subscribed else None,
                    "updated_at": datetime.now().isoformat()
                }).eq("id", user["id"]).execute()
                updated_count += 1
                logger.info(f"🔄 Обновлён статус подписки для {tg_id}: {current_status} -> {is_subscribed}")
        if updated_count > 0:
            logger.info(f"✅ Обновлено статусов подписки: {updated_count}")
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке подписок: {e}")


async def subscription_checker_worker():
    while True:
        await check_all_subscriptions()
        await asyncio.sleep(30)


# ========== КЛАВИАТУРЫ ==========

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🪢 Приступить к разбору")]],
    resize_keyboard=True
)

start_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🚀 Поехали!")]],
    resize_keyboard=True
)

q1_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Я не помню / Не хочу отвечать")]],
    resize_keyboard=True
)

q2_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Залипаю в соцсетях / сериалах / телефоне")],
        [KeyboardButton(text="🍕 Заедаю / закуриваю / выпиваю")],
        [KeyboardButton(text="💭 Зависаю в мыслях, прокручиваю одно и то же")],
        [KeyboardButton(text="😤 Срываюсь на близких")],
        [KeyboardButton(text="💪 Ухожу в активную работу / уборку / спорт до изнеможения")],
        [KeyboardButton(text="😶 Делаю вид, что ничего не случилось")],
        [KeyboardButton(text="✏️ Свой вариант")],
    ],
    resize_keyboard=True
)

q3_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❓ Сложно ответить")]],
    resize_keyboard=True
)

q4_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Да, постоянно")],
        [KeyboardButton(text="🔄 Иногда")],
        [KeyboardButton(text="📉 Редко")],
        [KeyboardButton(text="💚 Нет, я себя принимаю (или стараюсь)")],
    ],
    resize_keyboard=True
)

q5_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="😨 Я знаю, чего хочу, но мне страшно это сделать")],
        [KeyboardButton(text="😐 Я делаю много дел, но не чувствую удовлетворения")],
        [KeyboardButton(text="🎭 Я часто чувствую себя самозванцем даже в том, что умею")],
        [KeyboardButton(text="👥 Я завишу от мнения других больше, чем хотел(а) бы")],
        [KeyboardButton(text="🫠 Я устаю от людей и мечтаю побыть одна(ин)")],
        [KeyboardButton(text="✏️ Другое")],
    ],
    resize_keyboard=True
)

age_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="18–21"), KeyboardButton(text="22–25")],
        [KeyboardButton(text="26–30"), KeyboardButton(text="31–35")],
        [KeyboardButton(text="36–45"), KeyboardButton(text="45+")],
    ],
    resize_keyboard=True
)

gender_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👨 Мужской"), KeyboardButton(text="👩 Женский")],
        [KeyboardButton(text="Другое")],
    ],
    resize_keyboard=True
)

city_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🙅‍♂️ Не хочу указывать")],
    ],
    resize_keyboard=True
)


# ========== КОМАНДЫ ==========

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    
    # Сразу отвечаем, чтобы пользователь видел, что бот жив
    await message.answer("🤖 Бот работает! Давай начнём...")
    
    tg_id = message.from_user.id
    username = message.from_user.username
    name = message.from_user.first_name

    if has_user_completed_test(tg_id):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🧠 Наш канал", url=CHANNEL_LINK)]]
        )
        await message.answer(
            "😊 **Вы уже проходили этот опрос!**\n\n"
            "Спасибо за доверие. Я помню ваши ответы.\n\n"
            "Если хотите что-то уточнить или обсудить — напишите мне лично.\n\n"
            "А пока — подписывайтесь на мой канал, там я делюсь полезными мыслями о психологии.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    user_id, user = get_or_create_user(tg_id, username, name)
    if user_id is None:
        await message.answer("❌ Ошибка подключения к базе данных. Попробуйте позже.")
        return
    await state.update_data(user_id=user_id)
    await message.answer(
        "Привет.\n\n"
        "Меня зовут Андрей. Психолог-консультант с дипломом. "
        "Распутываю жизненные узлы на стыке психологии, философии и духовных практик.\n\n"
        "Здесь не будет шаблонных фраз и «диагнозов за 2 минуты». Я смотрю на человека иначе — "
        "через механизмы психики, а не ярлыки.\n\n"
        "Я веду этот бот не как машина. Как человек, который сам прошёл через стыд, "
        "погоню за достижениями и встречу с собой.",
        reply_markup=main_keyboard
    )


@dp.message(F.text == "🪢 Приступить к разбору")
async def more_info(message: types.Message, state: FSMContext):
    await message.answer(
        "Сейчас я задам тебе 6 вопросов. Они простые, но не всегда лёгкие. "
        "Не нужно придумывать красивые ответы — просто то, что приходит в голову.\n\n"
        "✏️ Зачем это?\n"
        "Я хочу увидеть твой запрос, твою точку напряжения. Тот самый «узел», который мешает дышать свободно.\n\n"
        "🎁 Что ты получишь?\n"
        "Через несколько часов (максимум завтра утром) я напишу тебе лично. "
        "Без шаблонов. С поддержкой, гипотезой и одним вопросом, который поможет тебе копнуть глубже.\n\n"
        "Это не автоответчик. Это разговор.\n\n"
        "Поехали?",
        reply_markup=start_keyboard
    )


@dp.message(F.text == "🚀 Поехали!")
async def start_questionnaire(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 **Вы уже проходили этот опрос!**\n\nСпасибо за доверие.", parse_mode="Markdown")
        return
    await state.set_state(Questionnaire.question1)
    await message.answer(
        "📝 **Вопрос 1 из 6**\n\n"
        "Какая ситуация за последний месяц вызвала у тебя самую сильную эмоцию?\n\n"
        "Это может быть тревога, злость, стыд, тоска, бессилие или что-то ещё.\n\n"
        "Не анализируй. Опиши коротко — пару предложений.",
        parse_mode="Markdown",
        reply_markup=q1_keyboard
    )


@dp.message(Questionnaire.question1)
async def answer_question1(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос. Спасибо!")
        await state.clear()
        return
    answer = message.text.strip()
    if answer == "❌ Я не помню / Не хочу отвечать":
        answer = "Не помню / Не хочет отвечать"
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        save_answer(user_id, 1, answer)
    await state.update_data(q1=answer)
    await state.set_state(Questionnaire.question2)
    await message.answer(
        "📝 **Вопрос 2 из 6**\n\n"
        "В той ситуации — или в любой другой, где тебе было тяжело, — что ты обычно делаешь?\n\n"
        "Выбери самый частый вариант:",
        parse_mode="Markdown",
        reply_markup=q2_keyboard
    )


@dp.message(Questionnaire.question2, F.text == "✏️ Свой вариант")
async def custom_answer_question2(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос.")
        await state.clear()
        return
    await message.answer("Напиши свой вариант:", reply_markup=ReplyKeyboardRemove())


@dp.message(Questionnaire.question2)
async def answer_question2(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос.")
        await state.clear()
        return
    answer = message.text.strip()
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        save_answer(user_id, 2, answer)
    await state.update_data(q2=answer)
    await state.set_state(Questionnaire.question3)
    await message.answer(
        "📝 **Вопрос 3 из 6**\n\n"
        "Если представить, что у этой эмоции или состояния есть лицо, форма, цвет или даже персонаж — что бы это было?\n\n"
        "Не думай слишком много. Первое, что приходит в голову.",
        parse_mode="Markdown",
        reply_markup=q3_keyboard
    )


@dp.message(Questionnaire.question3)
async def answer_question3(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос.")
        await state.clear()
        return
    answer = message.text.strip()
    if answer == "❓ Сложно ответить":
        answer = "Сложно ответить"
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        save_answer(user_id, 3, answer)
    await state.update_data(q3=answer)
    await state.set_state(Questionnaire.question4)
    await message.answer(
        "📝 **Вопрос 4 из 6**\n\n"
        "Бывает, что ты думаешь:\n"
        "«Я должен(на) быть сильнее / спокойнее / успешнее / собраннее, чем я есть»?",
        parse_mode="Markdown",
        reply_markup=q4_keyboard
    )


@dp.message(Questionnaire.question4)
async def answer_question4(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос.")
        await state.clear()
        return
    answer = message.text.strip()
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        save_answer(user_id, 4, answer)
    await state.update_data(q4=answer)
    await state.set_state(Questionnaire.question5)
    await message.answer(
        "📝 **Вопрос 5 из 6**\n\n"
        "Какое из утверждений звучит про тебя правдивее всего?",
        parse_mode="Markdown",
        reply_markup=q5_keyboard
    )


@dp.message(Questionnaire.question5, F.text == "✏️ Другое")
async def custom_answer_question5(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос.")
        await state.clear()
        return
    await message.answer("Напиши свой вариант:", reply_markup=ReplyKeyboardRemove())


@dp.message(Questionnaire.question5)
async def answer_question5(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос.")
        await state.clear()
        return
    answer = message.text.strip()
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        save_answer(user_id, 5, answer)
    await state.update_data(q5=answer)
    await state.set_state(Questionnaire.question6)
    await message.answer(
        "📝 **Вопрос 6 из 6. Последний.**\n\n"
        "А теперь представь на секунду, что ты проснулась(ся) через год и твоя жизнь немного изменилась.\n\n"
        "Что именно стало по-другому? Как ты себя чувствуешь? Что перестало тебя мучить? Что появилось?\n\n"
        "Опиши коротко — одним-двумя предложениями.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(Questionnaire.question6)
async def answer_question6(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос.")
        await state.clear()
        return
    answer = message.text.strip()
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        save_answer(user_id, 6, answer)
    await state.update_data(q6=answer)
    await state.set_state(Questionnaire.ask_name)
    await message.answer(
        "И напоследок — пара коротких уточнений. Это поможет мне увидеть твой контекст и не додумывать лишнего.\n\n"
        "Как к тебе обращаться?\n"
        "(Имя или псевдоним — как удобно)",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(Questionnaire.ask_name)
async def ask_name(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос.")
        await state.clear()
        return
    user_name = message.text.strip()
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        update_user_info(user_id, "user_name", user_name)
    await state.update_data(user_name=user_name)
    await state.set_state(Questionnaire.ask_age)
    await message.answer(
        "Сколько тебе лет?\n\n"
        "Выбери свой возрастной диапазон:",
        reply_markup=age_keyboard
    )


@dp.message(Questionnaire.ask_age)
async def ask_age(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос.")
        await state.clear()
        return
    age = message.text.strip()
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        update_user_info(user_id, "user_age", age)
    await state.update_data(user_age=age)
    await state.set_state(Questionnaire.ask_gender)
    await message.answer("Твой пол?", reply_markup=gender_keyboard)


@dp.message(Questionnaire.ask_gender)
async def ask_gender(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос.")
        await state.clear()
        return
    gender = message.text.strip()
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        update_user_info(user_id, "user_gender", gender)
    await state.update_data(user_gender=gender)
    await state.set_state(Questionnaire.ask_city)
    await message.answer(
        "Где ты сейчас?\n\n"
        "Город или страна. Среда иногда незаметно влияет на наши механизмы.\n\n"
        "Можешь написать или нажать кнопку пропуска.",
        reply_markup=city_keyboard
    )


@dp.message(Questionnaire.ask_city)
async def ask_city(message: types.Message, state: FSMContext):
    if has_user_completed_test(message.from_user.id):
        await message.answer("😊 Вы уже прошли этот опрос.")
        await state.clear()
        return
    city = message.text.strip()
    if city == "🙅‍♂️ Не хочу указывать":
        city = "Не указано"
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        update_user_info(user_id, "user_city", city)
        update_test_completed(user_id)
    await state.update_data(user_city=city)
    await state.clear()
    await message.answer(
        "🙏 **Спасибо. Твои ответы у меня.**\n\n"
        "Я прочитаю их сам и напишу тебе лично в Telegram — с гипотезой и поддержкой. Без диагнозов.\n\n"
        "Обычно отвечаю через несколько часов, максимум — завтра утром.\n\n"
        "**🧠 А ещё — если тебе интересна психология, саморазвитие и как работают наши механизмы психики...**\n\n"
        f"👉 [Подпишись на мой Telegram-канал]({CHANNEL_LINK})\n\n"
        "Там я делюсь мыслями, которые не влезают в бота, и отвечаю на вопросы подписчиков.\n\n"
        "До скорого. 👋",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


# ========== ЗАПУСК БОТА ==========

async def main():
    print("\n" + "="*50)
    print("🚀 БОТ ЗАПУЩЕН!")
    print("📦 Supabase подключён!")
    print("💬 Сохранение сообщений пользователей (только после теста)")
    print("="*50 + "\n")
    asyncio.create_task(message_queue_worker())
    asyncio.create_task(subscription_checker_worker())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
