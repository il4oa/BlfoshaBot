import requests
import aiohttp
from bs4 import BeautifulSoup
import random
import json
import os
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler, MessageHandler, filters
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.ext import Application, JobQueue, Job
import nest_asyncio
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display
import re

nest_asyncio.apply()
 
scheduled_quote = None
quote_status = {"approved": False, "approver": None, "time_remaining": None}

quote_base_url = "https://www.aldiwan.net/quote{}.html"
poem_base_url = "https://www.aldiwan.net/poem{}.html"
BOT_TOKEN = 'Your_Bot_Token'
USER_IDS_FILE = 'user_ids.json'
METRICS_FILE = 'bot_metrics.json'

PASSWORD = "ADMINPASSWORD"
ADMIN_ID = YOUR_TELEGRAM_ID
auto_schedule_task = None
auto_schedule_task = None  
auto_schedule_interval = None  
last_auto_sent_time = None  

metrics = {
    "messages_sent": 0,
    "users_interacted": set(),
    "errors": 0,
    "user_interactions": {} 
}


user_password_attempts = {}

logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


def display_metrics():
    os.system('clear' if os.name == 'posix' else 'cls')  
    print("📊 Bot Metrics:")
    print(f"✅ Total Messages Sent: {metrics['messages_sent']}")
    print(f"👥 Total Users Interacted: {len(metrics['users_interacted'])}")
    print(f"❌ Errors: {metrics['errors']}")
    print("\n📜 User Interactions:")
    
    
    for user_id, data in metrics["user_interactions"].items():
        username = data.get("username", "Unknown")
        interactions = data.get("interactions", 0)
        print(f"@{username} - {interactions} interactions")

async def periodic_metrics_display():
    while True:
        display_metrics()  
        await asyncio.sleep(10)  

async def periodic_save_metrics():
    while True:
        save_metrics()  
        await asyncio.sleep(60)

def load_metrics():
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, 'r') as file:
                loaded_metrics = json.load(file)
                
                loaded_metrics["users_interacted"] = set(loaded_metrics.get("users_interacted", []))
                return loaded_metrics
        except Exception as e:
            logger.error(f"Error loading metrics: {e}")
    
    return {
        "messages_sent": 0,
        "users_interacted": set(),
        "errors": 0,
        "user_interactions": {}
    }

def save_metrics():
    try:
        
        metrics["users_interacted"] = list(metrics["users_interacted"])
        with open(METRICS_FILE, 'w') as file:
            json.dump(metrics, file, indent=4)
        
        metrics["users_interacted"] = set(metrics["users_interacted"])
    except Exception as e:
        logger.error(f"Error saving metrics: {e}")




metrics = load_metrics()

def on_shutdown():
    save_metrics()
    logger.info("Metrics saved successfully on shutdown.")


async def fetch_quote_async(page_number):
    url = quote_base_url.format(page_number)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    soup = BeautifulSoup(await response.text(), "html.parser")
                    quote_divs = soup.find_all("h3")
                    quotes = [
                        div.text.strip() for div in quote_divs
                        if 'h3-i' not in div.get('class', []) and 'text-left' not in div.get('class', [])
                    ]
                    return "\n".join(quotes) if quotes else None
    except Exception as e:
        logger.error(f"Error scraping quote: {e}")
        metrics["errors"] += 1
    return None

async def get_random_quote():
    random_page_number = random.randint(1, 1435)
    return await fetch_quote_async(random_page_number)


async def fetch_poem_async(page_number):
    url = poem_base_url.format(page_number)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    soup = BeautifulSoup(await response.text(), "html.parser")
                    poem_div = soup.find("div", {"id": "poem_content"})
                    poem_lines = poem_div.find_all("h3", style="height: 28px;")
                    poem = "\n".join([line.text.strip() for line in poem_lines])
                    return poem if poem else None
    except Exception as e:
        logger.error(f"Error scraping poem: {e}")
        metrics["errors"] += 1
    return None


async def fetch_poem_writer(page_number):
    url = poem_base_url.format(page_number)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    soup = BeautifulSoup(await response.text(), "html.parser")
                    writer_tag = soup.find("div", class_="col-lg-5 col-md-6 col-12 float-left mosahmat_block_top")
                    if writer_tag:
                        writer = writer_tag.find("h2", class_="text-center h3 mt-3 mb-0")
                        if writer:
                            return writer.text.strip()
    except Exception as e:
        logger.error(f"Error scraping poem writer: {e}")
        metrics["errors"] += 1
    return "غير معروف"


async def get_random_poem():
    random_page_number = random.randint(0, 124852)
    poem = await fetch_poem_async(random_page_number)
    writer = await fetch_poem_writer(random_page_number)
    return poem, writer


def load_user_ids():
    try:
        with open(USER_IDS_FILE, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return []

def save_user_ids(user_ids):
    with open(USER_IDS_FILE, 'w') as file:
        json.dump(user_ids, file)

def update_user_ids(user_id, username=None):
    metrics["users_interacted"].add(user_id)

    if user_id in metrics["user_interactions"]:
        
        metrics["user_interactions"][user_id]["interactions"] += 1
    else:
        
        metrics["user_interactions"][user_id] = {"username": username, "interactions": 1}

    
    save_metrics()

async def broadcast_message(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await context.bot.send_message(chat_id, "You are not authorized to use this command.")
        return

    if len(context.args) < 1:
        await context.bot.send_message(chat_id, "Please provide a message to broadcast.")
        return
    
  
    message = " ".join(context.args)
    message = message.replace(r"\n", "\n")  

   
    for user_id in user_ids:
        try:
            await context.bot.send_message(user_id, message)
            logger.info(f"Sent message to {user_id}")
        except Exception as e:
            logger.error(f"Error broadcasting message to {user_id}: {e}")
    
    await context.bot.send_message(chat_id, "Broadcast message sent to all users!")

def format_arabic_text(text):
    """Format Arabic text with reshaping while keeping diacritics intact."""
    
    
    text_with_harakat = re.sub(r'[\u064B-\u0652]', '', text) 

    # Reshape the text without harakat
    reshaped_text = arabic_reshaper.reshape(text_with_harakat)
    
    
    index = 0
    result_text = list(reshaped_text)
    
   
    for i, char in enumerate(text):
        if char in '\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652':
            result_text.insert(i, char)  

    final_text = "".join(result_text)
    
    
    bidi_text = get_display(final_text)

    
    print(f"Original Text: {text}")
    print(f"Text without Harakat: {text_with_harakat}")
    print(f"Reshaped Text: {reshaped_text}")
    print(f"Final Text with Diacritics: {final_text}")
    print(f"Bidi Formatted Text: {bidi_text}")

    return bidi_text




def create_quote_image(quote, background_path, font_path, output_path):

    background = Image.open(background_path)
    draw = ImageDraw.Draw(background)


    font = ImageFont.truetype(font_path, size=50)

 
    formatted_quote = format_arabic_text(quote)

   
    lines = formatted_quote.split('\n')

  
    line_heights = [
        draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1]
        for line in lines
    ]
    total_text_height = sum(line_heights) + 10 * (len(lines) - 1)

   
    y_start = (background.height - total_text_height) // 2


    for index, line in enumerate(lines):
        text_bbox = draw.textbbox((0, 0), line, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

     
        text_x = background.width - text_width - 20

       
        if index % 2 == 1: 
            text_x -= 270

        text_y = y_start + sum(line_heights[:index]) + (index * 20)

       
        draw.text((text_x, text_y), line, fill="black", font=font)

   
    background.save(output_path, format='JPEG', quality=100, optimize=True)



async def fetch_random_quote(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username
    update_user_ids(user_id, username)

    quote_task = asyncio.create_task(get_random_quote())
    quote = await quote_task

    if quote:
        metrics["messages_sent"] += 1
        await context.bot.send_message(chat_id, quote)
        await send_buttons(update, context, "تم, يمكنك الأن اختيار احد هذه الخيارات :")
    else:
        metrics["errors"] += 1
        await context.bot.send_message(chat_id, "حاول مجدداً.")

async def fetch_random_poem(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username
    update_user_ids(user_id, username)

    poem_task = asyncio.create_task(get_random_poem())
    poem, writer = await poem_task

    if poem:
        metrics["messages_sent"] += 1
        message = f"{poem}\n\nللشاعر : {writer}"
        await context.bot.send_message(chat_id, message)
        await send_buttons(update, context, "تم, يمكنك الأن اختيار احد هذه الخيارات :")
    else:
        metrics["errors"] += 1
        await context.bot.send_message(chat_id, "لم يتم العثور على قصيدة عشوائية، حاول مجدداً.")

async def handle_button_click(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == "random_quote":
        await fetch_random_quote(update, context)
    elif query.data == "random_poem":
        await fetch_random_poem(update, context)
    elif query.data == "aja_program":
        await query.message.reply_text(
            text="📽️ برنامج اجا: https://www.tiktok.com/@blfosha_ar/video/7426030995897388306"
        )

        
        keyboard = [
            [InlineKeyboardButton("✍️بيت عشوائي", callback_data="random_quote")],
            [InlineKeyboardButton("✍️قصيدة عشوائية", callback_data="random_poem")],
            [InlineKeyboardButton("🖼️ صورة اقتباس", callback_data="generate_quote_image")],
            [InlineKeyboardButton("📽️برنامج اجا", callback_data="aja_program")],
            [InlineKeyboardButton("📌قناة بالفصحى", url="https://t.me/Blfosh_AR")],
            [InlineKeyboardButton("📌حساب بالفصحى", url="https://twitter.com/blfosha")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(
            text="تم, يمكنك الأن اختيار احد هذه الخيارات :",
            reply_markup=reply_markup
        )


async def send_buttons(update: Update, context: CallbackContext, message_text: str):
    chat_id = update.effective_chat.id
    keyboard = [
        [InlineKeyboardButton("✍️بيت عشوائي", callback_data="random_quote")],
        [InlineKeyboardButton("✍️قصيدة عشوائية", callback_data="random_poem")],
        [InlineKeyboardButton("🖼️ صورة اقتباس", callback_data="generate_quote_image")],
        [InlineKeyboardButton("📽️برنامج اجا", callback_data="aja_program")],
        [InlineKeyboardButton("📌قناة بالفصحى", url="https://t.me/Blfosh_AR")],
        [InlineKeyboardButton("📌حساب بالفصحى", url="https://twitter.com/blfosha")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id, message_text, reply_markup=reply_markup)

async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    username = update.effective_user.username
    update_user_ids(user_id, username)
    await send_buttons(update, context, "اهلاً بك في بوت بالفصحى \nللحصول على اقتباسات عشوائية أو قصائد.")
def save_metrics():
    try:
        
        metrics["users_interacted"] = list(metrics["users_interacted"])
        
        with open(METRICS_FILE, 'w') as file:
            json.dump(metrics, file)
        
        
        metrics["users_interacted"] = set(metrics["users_interacted"])
    except Exception as e:
        logger.error(f"Error saving metrics: {e}")

def load_metrics():
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, 'r') as file:
                return json.load(file)
        except Exception as e:
            logger.error(f"Error loading metrics: {e}")
    return metrics


def update_user_ids(user_id, username=None):
    metrics["users_interacted"].add(user_id)
    if user_id not in metrics["user_interactions"]:
        metrics["user_interactions"][user_id] = {"username": username, "interactions": 0}
    
    metrics["user_interactions"][user_id]["interactions"] += 1
    user_ids = load_user_ids()
    if user_id not in user_ids:
        user_ids.append(user_id)
        save_user_ids(user_ids)

    
    save_metrics()

async def handle_generate_quote_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    
    quote = await get_random_quote()

    if quote:
       
        background_path = r"C:\Users\yaman\Desktop\Blfosha-Project\background1.png"
        font_path = r"C:\Users\yaman\Desktop\Blfosha-Project\Amiri-Bold.ttf"
        output_image_path = r"C:\Users\yaman\Desktop\Blfosha-Project\output_image.jpg"

        try:
            create_quote_image(quote, background_path, font_path, output_image_path)

            
            with open(output_image_path, 'rb') as image_file:
                await context.bot.send_photo(chat_id, photo=image_file)

           
            message = "تم, يمكنك الأن اختيار احد هذه الخيارات :"
            keyboard = [
                [InlineKeyboardButton("✍️بيت عشوائي", callback_data="random_quote")],
                [InlineKeyboardButton("✍️قصيدة عشوائية", callback_data="random_poem")],
                [InlineKeyboardButton("🖼️ صورة اقتباس", callback_data="generate_quote_image")],
                [InlineKeyboardButton("📽️برنامج اجا", callback_data="aja_program")],
                [InlineKeyboardButton("📌قناة بالفصحى", url="https://t.me/Blfosh_AR")],
                [InlineKeyboardButton("📌حساب بالفصحى", url="https://twitter.com/blfosha")]
            ]

            
            await context.bot.send_message(
                chat_id,
                message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        except ValueError as e:
            await context.bot.send_message(chat_id, "حدث خطأ أثناء إنشاء الصورة.")
            logger.error(e)
    else:
        await context.bot.send_message(chat_id, "حاول مجدداً.")  

async def show_data(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    logger.info(f"User ID {user_id} is trying to access data.")
    
    if user_password_attempts.get(user_id, False):
        user_interactions = metrics["user_interactions"]
        data_message = "📊 **بيانات البوت**\n\n"
        data_message += f"✅ عدد الرسائل المرسلة: {metrics['messages_sent']}\n"
        data_message += f"👥 عدد المستخدمين المتفاعلين: {len(metrics['users_interacted'])}\n"
        data_message += f"❌ الأخطاء: {metrics['errors']}\n\n"
        data_message += "📜 **تفاعلات المستخدمين**:\n"
        
        for user_id, data in user_interactions.items():
            data_message += f"@{data['username']} - تفاعل: {data['interactions']} مرة\n"
        
        await context.bot.send_message(chat_id, data_message)
    else:
        logger.info(f"User ID {user_id} has not entered the correct password.")
        await context.bot.send_message(chat_id, "للوصول الى البيانات، يرجى ادخال كلمة السر.")

async def handle_password(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    logger.info(f"User ID {user_id} attempted to enter password.")
    
    if len(context.args) == 1:
        password = context.args[0]
        logger.info(f"Password entered: {password}")
        
        if password == PASSWORD:
            user_password_attempts[user_id] = True
            await context.bot.send_message(update.effective_chat.id, "تم التحقق! يمكنك الآن الوصول للبيانات.")
            logger.info(f"Password for user {user_id} is correct. Access granted.")
        else:
            await context.bot.send_message(update.effective_chat.id, "كلمة السر غير صحيحة.")
            logger.warning(f"Incorrect password entered for user {user_id}.")
    else:
        await context.bot.send_message(update.effective_chat.id, "يرجى إدخال كلمة السر.")
        logger.info(f"User ID {user_id} has not entered a password yet.")  


async def send_random_quote_to_all(context: CallbackContext):
    global scheduled_quote
    global quote_status

    if not scheduled_quote or not quote_status["approved"]:
        print("----------------")
        print("No approved quote to send.")
        print("----------------")
        return

    user_ids = load_user_ids()
    sent_count = 0

    for user_id in user_ids:
        try:
            await context.bot.send_message(user_id, scheduled_quote)
            sent_count += 1
            metrics["messages_sent"] += 1
        except Exception as e:
            logger.error(f"Error sending quote to {user_id}: {e}")
            metrics["errors"] += 1

    print("----------------")
    print(f'done sending "{scheduled_quote}"')
    print(f"To: {sent_count} users!")
    print("----------------")

    
    scheduled_quote = None
    quote_status = {"approved": False, "approver": None, "time_remaining": None}

async def check_quote(update: Update, context: CallbackContext):
    global scheduled_quote
    global quote_status

    chat_id = update.effective_chat.id

    
    if scheduled_quote is None:
        scheduled_quote = await get_random_quote()
        quote_status["approved"] = False

    
    keyboard = [
        [InlineKeyboardButton("Approve", callback_data="approve_quote"),
         InlineKeyboardButton("ReRoll", callback_data="reroll_quote")],
        [InlineKeyboardButton("Auto", callback_data="auto_schedule")],
        [InlineKeyboardButton("Check Status", callback_data="check_status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    
    await context.bot.send_message(
        chat_id,
        f"Current quote:\n\n\"{scheduled_quote}\"\n\nDo you approve the quote?",
        reply_markup=reply_markup
    )



async def display_status(update: Update, context: CallbackContext):
    global scheduled_quote
    global quote_status
    global auto_schedule_task
    global auto_schedule_interval
    global last_auto_sent_time

    chat_id = update.effective_chat.id

    
    if scheduled_quote and quote_status.get("time_remaining"):
        hours, remainder = divmod(quote_status["time_remaining"], 3600)
        minutes, seconds = divmod(remainder, 60)
        scheduled_quote_status = (
            f"Scheduled Quote:\n-------------------\n\"{scheduled_quote}\"\n\n"
            f"Will be sent after:\n"
            f"{int(hours)} hours : {int(minutes)} minutes : {int(seconds)} seconds\n"
            "-------------------\n"
        )
    else:
        scheduled_quote_status = "No scheduled quote currently.\n"

    
    if auto_schedule_task and not auto_schedule_task.cancelled():
        if last_auto_sent_time and auto_schedule_interval:
            time_since_last_sent = (datetime.now() - last_auto_sent_time).total_seconds()
            time_until_next_sent = auto_schedule_interval - time_since_last_sent

            last_sent_hours, last_sent_remainder = divmod(time_since_last_sent, 3600)
            last_sent_minutes, last_sent_seconds = divmod(last_sent_remainder, 60)

            next_sent_hours, next_sent_remainder = divmod(time_until_next_sent, 3600)
            next_sent_minutes, next_sent_seconds = divmod(next_sent_remainder, 60)

            auto_status = (
                f"Auto Mode Status:\n-------------------\n"
                f"Last quote sent:\n"
                f"Before {int(last_sent_hours)} hours : {int(last_sent_minutes)} minutes : {int(last_sent_seconds)} seconds\n\n"
                f"Next quote:\n"
                f"After {int(next_sent_hours)} hours : {int(next_sent_minutes)} minutes : {int(next_sent_seconds)} seconds\n"
                "-------------------\n"
            )
        else:
            auto_status = "Auto mode is active, but no quotes have been sent yet.\n"
    else:
        auto_status = "Auto mode is not active.\n"

    
    await context.bot.send_message(chat_id, scheduled_quote_status + auto_status)

async def track_quote_time():
    while True:
        if quote_status["time_remaining"] is not None:
            quote_status["time_remaining"] -= 1
            if quote_status["time_remaining"] <= 0:
                quote_status["time_remaining"] = None
                print(f"Time is up. Sending approved quote: \"{scheduled_quote}\"")
                
                context = CallbackContext.from_application(application)
                await send_random_quote_to_all(context)
        await asyncio.sleep(1)
async def activate_auto_mode(hours, query):
    global auto_schedule_task

    interval_seconds = hours * 3600

    
    if auto_schedule_task:
        auto_schedule_task.cancel()

    
    auto_schedule_task = asyncio.create_task(auto_send_quotes(interval_seconds))

    await query.edit_message_text(
        text=f"Auto mode activated! A new quote will be sent every {hours} hour(s)."
    )
async def auto_send_quotes(interval_seconds):
    global scheduled_quote

    while True:
        
        scheduled_quote = await get_random_quote()

        
        user_ids = load_user_ids()
        for user_id in user_ids:
            try:
                await context.bot.send_message(user_id, scheduled_quote)
                metrics["messages_sent"] += 1
            except Exception as e:
                logger.error(f"Error sending quote to {user_id}: {e}")
                metrics["errors"] += 1

        await asyncio.sleep(interval_seconds)
async def handle_quote_buttons(update: Update, context: CallbackContext):
    global scheduled_quote
    global quote_status

    query = update.callback_query
    action = query.data

    await query.answer() 

    if action == "approve_quote":
        quote_status["approved"] = True
        await query.edit_message_text(
            text=f"Quote approved:\n\n\"{scheduled_quote}\"\n\nWhen should it be sent?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("1 Hour", callback_data="schedule_1_hour"),
                 InlineKeyboardButton("2 Hours", callback_data="schedule_2_hours")], 
                [InlineKeyboardButton("3 Hours", callback_data="schedule_3_hours"),
                 InlineKeyboardButton("4 Hours", callback_data="schedule_4_hours")],
                [InlineKeyboardButton("5 Hours", callback_data="schedule_5_hours")]
            ])
        )
    elif action == "reroll_quote":
        scheduled_quote = await get_random_quote()
        quote_status["approved"] = False
        await query.edit_message_text(
            text=f"This is the new quote:\n\n\"{scheduled_quote}\"\n\nDo you approve the quote?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Approve", callback_data="approve_quote"),
                 InlineKeyboardButton("ReRoll", callback_data="reroll_quote")]
            ])
        )
    elif action.startswith("schedule_"):
        
        hours = int(action.split("_")[1])
        quote_status["time_remaining"] = hours * 3600

        print(f"Scheduled a quote for {hours} hour(s). Time remaining: {quote_status['time_remaining']} seconds")

        await query.edit_message_text(
            text=f"Scheduled! The quote will be sent in {hours} hour(s)."
        )
    elif action == "auto_schedule":
        
        await query.edit_message_text(
            text="Choose how often to send a quote automatically:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Every 1 Hour", callback_data="auto_1_hour"),
                 InlineKeyboardButton("Every 2 Hours", callback_data="auto_2_hours")],
                [InlineKeyboardButton("Every 3 Hours", callback_data="auto_3_hours"),
                 InlineKeyboardButton("Every 4 Hours", callback_data="auto_4_hours")],
                [InlineKeyboardButton("Every 5 Hours", callback_data="auto_5_hours")]
            ])
        )
    elif action == "check_status":
        
        await display_status(update, context)

async def display_status(update: Update, context: CallbackContext):
    global scheduled_quote
    global quote_status
    global auto_schedule_task
    global last_auto_sent_time
    global auto_schedule_interval

    chat_id = update.effective_chat.id

    
    if scheduled_quote and quote_status.get("time_remaining") is not None:
        
        hours, remainder = divmod(quote_status["time_remaining"], 3600)
        minutes, seconds = divmod(remainder, 60)

        scheduled_quote_status = (
            f"Scheduled Quote:\n-------------------\n\"{scheduled_quote}\"\n\n"
            f"Will be sent after:\n"
            f"{int(hours)} hours : {int(minutes)} minutes : {int(seconds)} seconds\n"
            "-------------------\n"
        )
    else:
        scheduled_quote_status = "No scheduled quote currently.\n"

    
    if auto_schedule_task and not auto_schedule_task.cancelled():
        if last_auto_sent_time and auto_schedule_interval:
            time_since_last_sent = (datetime.now() - last_auto_sent_time).total_seconds()
            time_until_next_sent = auto_schedule_interval - time_since_last_sent

            last_sent_hours, last_sent_remainder = divmod(time_since_last_sent, 3600)
            last_sent_minutes, last_sent_seconds = divmod(last_sent_remainder, 60)

            next_sent_hours, next_sent_remainder = divmod(time_until_next_sent, 3600)
            next_sent_minutes, next_sent_seconds = divmod(next_sent_remainder, 60)

            auto_status = (
                f"Auto Mode Status:\n-------------------\n"
                f"Last quote sent:\n"
                f"Before {int(last_sent_hours)} hours : {int(last_sent_minutes)} minutes : {int(last_sent_seconds)} seconds\n\n"
                f"Next quote:\n"
                f"After {int(next_sent_hours)} hours : {int(next_sent_minutes)} minutes : {int(next_sent_seconds)} seconds\n"
                "-------------------\n"
            )
        else:
            auto_status = "Auto mode is active, but no quotes have been sent yet.\n"
    else:
        auto_status = "Auto mode is not active.\n"

    
    await context.bot.send_message(chat_id, scheduled_quote_status + auto_status)

async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("data", show_data))
    application.add_handler(CommandHandler("password", handle_password))
    application.add_handler(CommandHandler("check", check_quote))  
    application.add_handler(CommandHandler("br", broadcast_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))
 
    
    application.add_handler(CallbackQueryHandler(handle_generate_quote_image, pattern="generate_quote_image"))
    application.add_handler(CallbackQueryHandler(handle_button_click))
    application.add_handler(CallbackQueryHandler(handle_button_click, pattern="random_.*"))  
    application.add_handler(CallbackQueryHandler(handle_quote_buttons, pattern="(approve_quote|reroll_quote|auto_schedule|auto_.*|schedule_.*)"))
    application.add_handler(CallbackQueryHandler(handle_quote_buttons, pattern="(approve_quote|reroll_quote|auto_schedule|check_status|auto_.*|schedule_.*)"))
    application.add_handler(CallbackQueryHandler(handle_quote_buttons, pattern="(approve_quote|reroll_quote|auto_schedule|check_status|schedule_.*|auto_.*)"))

    
    job_queue = application.job_queue
    job_queue.run_repeating(send_random_quote_to_all, interval=7200, first=0)

   
    metrics_display_task = asyncio.create_task(periodic_metrics_display())  
    metrics_save_task = asyncio.create_task(periodic_save_metrics())  
    quote_timer_task = asyncio.create_task(track_quote_time())   

    try:
        await application.run_polling()  
    finally:
        
        metrics_display_task.cancel()
        metrics_save_task.cancel()
        quote_timer_task.cancel()
        await asyncio.gather(metrics_display_task, metrics_save_task, quote_timer_task, return_exceptions=True)
        save_metrics()  
        print("Shutdown complete. Metrics saved.")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()  
    loop.run_until_complete(main())  
