import re
import random
import json
import logging
import os
import io
import requests
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler
)
from apscheduler.schedulers.background import BackgroundScheduler

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
WARN_LIMIT = 3
FLOOD_LIMIT = 5
FLOOD_WINDOW = 10

# ========== RANK CARD IMAGE GENERATOR ========== #
class RankCardGenerator:
    def create_rank_card(self, user_data: dict) -> io.BytesIO:
        """Create rank card image"""
        width, height = 600, 300
        image = Image.new('RGB', (width, height), color='#2C2F33')
        draw = ImageDraw.Draw(image)
        
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
            normal_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
            small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            title_font = ImageFont.load_default()
            normal_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
        
        level = user_data['level']
        rank = user_data['rank']
        username = user_data['username']
        display_name = user_data['name']
        current_xp = user_data['xp']
        xp_needed = level * user_data['settings']['xp_per_level']
        
        # Draw background
        draw.rectangle([0, 0, width, height], fill='#2C2F33')
        
        # Progress bar
        progress_bg = [50, 180, width - 50, 200]
        draw.rectangle(progress_bg, fill='#40444B')
        
        progress_width = int((current_xp / xp_needed) * (width - 100))
        if progress_width > 0:
            progress_fill = [50, 180, 50 + progress_width, 200]
            draw.rectangle(progress_fill, fill='#43B581')
        
        # Level circle
        level_circle_pos = (width - 80, 60)
        level_circle_radius = 30
        draw.ellipse([
            level_circle_pos[0] - level_circle_radius,
            level_circle_pos[1] - level_circle_radius,
            level_circle_pos[0] + level_circle_radius,
            level_circle_pos[1] + level_circle_radius
        ], fill='#7289DA')
        
        # User avatar
        avatar_size = 80
        avatar_pos = (50, 50)
        draw.ellipse([
            avatar_pos[0], avatar_pos[1],
            avatar_pos[0] + avatar_size, avatar_pos[1] + avatar_size
        ], fill='#7289DA')
        
        # User initial
        initial = display_name[0].upper() if display_name else "U"
        try:
            bbox = draw.textbbox((0, 0), initial, font=title_font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = avatar_pos[0] + (avatar_size - text_width) // 2
            y = avatar_pos[1] + (avatar_size - text_height) // 2
            draw.text((x, y), initial, fill='#FFFFFF', font=title_font)
        except:
            pass
        
        # Text elements
        draw.text((150, 40), display_name, fill='#FFFFFF', font=title_font)
        draw.text((150, 75), f"@{username}", fill='#99AAB5', font=small_font)
        draw.text((level_circle_pos[0] - 25, level_circle_pos[1] - 45), "LEVEL", fill='#99AAB5', font=small_font)
        draw.text((level_circle_pos[0] - 10, level_circle_pos[1] - 15), str(level), fill='#FFFFFF', font=title_font)
        draw.text((50, 150), f"RANK #{rank}", fill='#99AAB5', font=small_font)
        draw.text((width - 200, 150), f"{current_xp} / {xp_needed} XP", fill='#FFFFFF', font=normal_font)
        
        progress_percent = int((current_xp / xp_needed) * 100)
        draw.text((width - 80, 210), f"{progress_percent}%", fill='#99AAB5', font=small_font)
        
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return img_byte_arr

rank_generator = RankCardGenerator()

# ========== RANK TITLES SYSTEM ========== #
RANK_TITLES = {
    1: "🐣 Beginner", 2: "🚀 Rookie", 3: "⭐ Apprentice", 4: "🔥 Active", 5: "💪 Moderate",
    6: "🎯 Skilled", 7: "🏆 Pro", 8: "👑 Expert", 9: "💻 Coder", 10: "⚡ Programmer",
    11: "🔒 Hacker", 12: "🤖 Developer", 13: "🎮 Gamer", 14: "📊 Analyst", 15: "🚀 Specialist",
    16: "🌟 Master", 17: "💎 Elite", 18: "🏅 Champion", 19: "👨‍💻 Architect", 20: "🦄 Unicorn",
    21: "⚡ Ninja", 22: "🎯 Sniper", 23: "🔥 Phoenix", 24: "🌟 Superstar", 25: "👑 King",
    26: "🤯 Legend", 27: "💫 Mythic", 28: "🚀 Galactic", 29: "🌈 Eternal", 30: "👁️ God"
}

def get_rank_title(level: int) -> str:
    if level <= 0: return "🐣 Beginner"
    elif level > len(RANK_TITLES): return RANK_TITLES[len(RANK_TITLES)]
    else: return RANK_TITLES.get(level, "🐣 Beginner")

def generate_progress_bar(percentage: int, length: int = 15) -> str:
    filled = round(percentage / 100 * length)
    return f"┃{'█' * filled}{'━' * (length - filled)}┃"

# ========== COMPLETE DATA STORAGE ========== #
user_data = {
    'warnings': {},
    'flood': {},
    'message_counts': {},
    'welcome_message': "Welcome {name} (@{username}) to {chat}!",
    'goodbye_message': "Goodbye {name}! We'll miss you!",
    'banned_words': ["badword1", "badword2"],
    'custom_responses': {
        'greetings': ["Hello {name}! 👋", "Hi there {name}! 😊", "Hey {name}! How's it going?"],
        'farewells': ["Bye {name}! 👋", "See you later {name}! 😊", "Take care {name}!"],
        'thanks': ["You're welcome {name}! 😊", "Anytime {name}! 👍", "No problem {name}! 😄"]
    },
    'enabled_features': {
        'anti_spam': True, 'auto_mute': True, 'keyword_filter': True, 'flood_control': True,
        'welcome_message': True, 'goodbye_message': True, 'custom_responses': True,
        'meme': True, 'video': True, 'greet_users': True, 'anti_link': True,
        'report_system': True, 'message_counter': True, 'random_emoji': True,
        'ranking_system': True, 'truth_or_dare': True, 'word_games': True, 'meme_categories': True
    },
    'meme_categories': {
        'enabled': ['funny', 'programming', 'animals', 'gaming'],
        'user_favorites': {}
    },
    'truth_or_dare': {
        'truths': [
            "What's your most embarrassing moment?", "Have you ever cheated in an exam?",
            "What's the weirdest thing you've ever eaten?", "What's your biggest fear?",
            "What's the most trouble you've ever gotten into?", "What's your most annoying habit?",
            "What's something you're secretly proud of?", "What's the biggest lie you've ever told?"
        ],
        'dares': [
            "Send a voice message singing for 30 seconds", "Post a childhood photo in this chat",
            "Text your crush right now and screenshot it", "Do 10 pushups right now",
            "Speak in an accent for the next 5 messages", "Tell a funny joke to the group"
        ],
        'active_players': {}
    },
    'word_games': {
        'active_games': {},
        'word_bank': [
            {'word': 'algorithm', 'hint': 'Step-by-step procedure', 'category': 'tech'},
            {'word': 'blockchain', 'hint': 'Decentralized digital ledger', 'category': 'tech'},
            {'word': 'nebulous', 'hint': 'Vague or ill-defined', 'category': 'general'},
            {'word': 'quantum', 'hint': 'Relating to quantum mechanics', 'category': 'science'},
            {'word': 'syntax', 'hint': 'Arrangement in programming', 'category': 'tech'}
            MEME_URLS = [
    "https://i.imgflip.com/30b1gx.jpg",
    "https://i.imgflip.com/1bij.jpg",
    "https://i.imgflip.com/1g8my4.jpg",
    "https://i.imgflip.com/1otk96.jpg",
    "https://i.imgflip.com/261o3j.jpg",
    "https://i.imgflip.com/1c1uej.jpg",
    "https://i.imgflip.com/1h7in3.jpg",
    "https://i.imgflip.com/1e7ql7.jpg",
    "https://i.imgflip.com/1b42wb.jpg",
    "https://i.imgflip.com/1bim.jpg",
    "https://i.imgflip.com/1bip.jpg",
    "https://i.imgflip.com/1bix.jpg",
    "https://i.imgflip.com/1bgw.jpg",
    "https://i.imgflip.com/1bhf.jpg",
    "https://i.imgflip.com/1bhk.jpg",
    "https://i.imgflip.com/1bh8.jpg",
    "https://i.imgflip.com/1bhm.jpg",
    "https://i.imgflip.com/1bhn.jpg",
    "https://i.imgflip.com/1bh3.jpg",
    "https://i.imgflip.com/1bh1.jpg",
    "https://i.imgflip.com/1bh5.jpg",
    "https://i.imgflip.com/1bh6.jpg",
    "https://i.imgflip.com/1bh7.jpg",
    "https://i.imgflip.com/1bh9.jpg",
    "https://i.imgflip.com/1bh0.jpg",
    "https://i.imgflip.com/1bh2.jpg",
    "https://i.imgflip.com/1bh4.jpg",
    "https://i.imgflip.com/1bha.jpg",
    "https://i.imgflip.com/1bhb.jpg",
    "https://i.imgflip.com/1bhc.jpg"
]
                     GIF_MEMES = [
    # Popular GIF Memes
    "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",  # Michael Jackson eating popcorn
    "https://media.giphy.com/media/3o7aCTPPm4OHfRLSH6/giphy.gif",  # Success kid
    "https://media.giphy.com/media/l0HlRnAWXxn0Mlklq/giphy.gif",   # Dancing hotdog
    "https://media.giphy.com/media/26uf759LlDftqZNVm/giphy.gif",   # Crying cat
    "https://media.giphy.com/media/l0MYEqEzwMWFCg8rm/giphy.gif",   # Laughing crying emoji
    "https://media.giphy.com/media/3o72FfM5HJydzafgUE/giphy.gif",  # Mind blown
    "https://media.giphy.com/media/l0HlBO7eyXzSZkJri/giphy.gif",   # Facepalm
    "https://media.giphy.com/media/3o7abGQa0aRsohveXK/giphy.gif",  # Surprised Pikachu
    "https://media.giphy.com/media/l0Exk8EUzSLq8z22A/giphy.gif",   # Evil laugh
    "https://media.giphy.com/media/3o7TKSha51ATTx9KzC/giphy.gif",  # Running away
    
    # Reaction GIFs
    "https://media.giphy.com/media/3o7aD2saQhRlQV73EQ/giphy.gif",  # Thumbs up
    "https://media.giphy.com/media/l0MYC0LajbaPoEADu/giphy.gif",   # Slow clap
    "https://media.giphy.com/media/3o7WTGhpDf1R5Wx72Y/giphy.gif",  # Eye roll
    "https://media.giphy.com/media/l0HlTYWKW2j0pw5bi/giphy.gif",   # Shrug
    "https://media.giphy.com/media/3o7TKr3eGmhqNkoXh6/giphy.gif",  # Nodding yes
    "https://media.giphy.com/media/l0HlNrhRXKxK1QNnq/giphy.gif",   # Shaking head no
    
    # Animal GIFs
    "https://media.giphy.com/media/3o7abBphHJngINCHio/giphy.gif",  # Excited dog
    "https://media.giphy.com/media/JIX9t2j0ZTN9S/giphy.gif",       # Cat typing
    "https://media.giphy.com/media/13CoXDiaCcCoyk/giphy.gif",      # Puppy eyes
    "https://media.giphy.com/media/3o85xGocUH8RYoDKKs/giphy.gif",  # Dancing parrot
    "https://media.giphy.com/media/3o7TKsQ7X1Pm5mQvWM/giphy.gif",  # Bunny eating
    
    # Funny Moments
    "https://media.giphy.com/media/l0HlSHXwzmxqdQkBy/giphy.gif",   # Laughing on floor
    "https://media.giphy.com/media/3o7aD4Rf3E0zRkZQzC/giphy.gif",  # Spitting drink
    "https://media.giphy.com/media/l0HlNpBfYxGzKk3bi/giphy.gif",   # Falling down
    "https://media.giphy.com/media/3o7TKsQ7X1Pm5mQvWM/giphy.gif",  # Confused math
    "https://media.giphy.com/media/l0HlTYWKW2j0pw5bi/giphy.gif",   # This is fine (dog in fire)
    
    # Celebrity GIFs
    "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",   # Leonardo DiCaprio cheers
    "https://media.giphy.com/media/3o7aD4Rf3E0zRkZQzC/giphy.gif",  # Will Smith confused
    "https://media.giphy.com/media/l0HlNpBfYxGzKk3bi/giphy.gif",   # Johnny Depp drinking
    "https://media.giphy.com/media/3o7TKsQ7X1Pm5mQvWM/giphy.gif",  # Ryan Reynolds laughing
    "https://media.giphy.com/media/l0HlTYWKW2j0pw5bi/giphy.gif"    # The Rock eyebrow
]
        ],
        'categories': ['tech', 'science', 'general']
    },
    'ranking': {
        'users': {},
        'settings': {
            'xp_per_level': 400, 'daily_bonus': 50, 'streak_bonus': {3: 100, 7: 300},
            'message_xp_range': [1, 5], 'voice_message_xp': 10, 'photo_message_xp': 8
        },
        'leaderboard_cache': [],
        'last_update': None
    },
    'link_protection': {
        'allowed_domains': ["youtube.com", "telegram.org", "github.com", "wikipedia.org"],
        'blocked_domains': ["download.com", "malware.site", "virus.com"],
        'mode': "whitelist",
        'advanced': {'block_shorteners': True, 'block_obfuscated': True, 'allow_subdomains': False}
    },
    'auto_responses': {
        'patterns': {
            r'(?i)how are you': ["I'm doing great! 😊", "Feeling awesome! 👍"],
            r'(?i)thank you': ["You're welcome! 😊", "No problem! 👍"],
            r'(?i)good night': ["Good night! 🌙", "Sleep well! 😴"],
            r'(?i)good morning': ["Good morning! ☀️", "Morning! 😊"]
        }
    }
}

# ========== EXPANDED DATABASES ========== #
MEME_DATABASE = {
    'funny': ["https://i.imgflip.com/30b1gx.jpg", "https://i.imgflip.com/1bij.jpg", "https://i.imgflip.com/1g8my4.jpg"],
    'programming': ["https://i.imgflip.com/2h6y5t.jpg", "https://i.imgflip.com/2/1hl0b5.jpg"],
    'animals': ["https://i.imgflip.com/1o3j1p.jpg", "https://i.imgflip.com/1o3j2q.jpg"],
    'gaming': ["https://i.imgflip.com/1o3k1p.jpg", "https://i.imgflip.com/1o3k2q.jpg"],
    'reaction': ["https://i.imgflip.com/1o3l1p.jpg", "https://i.imgflip.com/1o3l2q.jpg"]
}

SHORT_VIDEOS = {
    'funny': [
        {"url": "https://sample-videos.com/video123/mp4/360/big_buck_bunny_360p_5mb.mp4", "caption": "😂 Funny Moment"},
        {"url": "https://sample-videos.com/video123/mp4/720/big_buck_bunny_720p_10mb.mp4", "caption": "😆 Hilarious Clip"}
    ],
    'gaming': [
        {"url": "https://sample-videos.com/video123/mp4/360/big_buck_bunny_360p_5mb.mp4", "caption": "🎮 Gaming Moment"},
        {"url": "https://sample-videos.com/video123/mp4/720/big_buck_bunny_720p_10mb.mp4", "caption": "⚡ Gaming Fail"}
    ]
}

VIDEO_DATABASE = {
    "360": [{"url": "https://sample-videos.com/video123/mp4/360/big_buck_bunny_360p_5mb.mp4", "caption": "360p Sample"}],
    "720": [{"url": "https://sample-videos.com/video123/mp4/720/big_buck_bunny_720p_10mb.mp4", "caption": "720p HD"}],
    "1080": [{"url": "https://sample-videos.com/video123/mp4/1080/big_buck_bunny_1080p_50mb.mp4", "caption": "1080p Full HD"}],
    "4k": [{"url": "https://example.com/4k-sample.mp4", "caption": "4K Ultra HD"}]
}

# ========== UTILITY FUNCTIONS ========== #
async def is_admin(update: Update) -> bool:
    return update.effective_user.id in [
        admin.user.id for admin in await update.effective_chat.get_administrators()
    ]

def clean_domain(url: str) -> str:
    return re.sub(r'^https?://|www\.', '', url.split('/')[0].lower())

def update_leaderboard():
    users = user_data['ranking']['users']
    user_data['ranking']['leaderboard_cache'] = sorted(
        users.keys(), key=lambda uid: (-users[uid]['level'], -users[uid]['xp'], users[uid]['last_active'])
    )
    user_data['ranking']['last_update'] = datetime.now()

def is_shortener(domain: str) -> bool:
    shorteners = ['bit.ly', 'goo.gl', 't.co', 'tinyurl.com']
    return any(s in domain for s in shorteners)

def is_obfuscated(domain: str) -> bool:
    patterns = [r'\d', r'[^\w.-]', r'([a-z])\1{2,}']
    return any(re.search(p, domain) for p in patterns)

# ========== RANKING SYSTEM ========== #
async def handle_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['ranking_system']:
        return

    user_id = update.effective_user.id
    user = user_data['ranking']['users'].setdefault(user_id, {
        'name': update.effective_user.first_name, 'username': update.effective_user.username or "",
        'xp': 0, 'level': 1, 'daily_streak': 0, 'last_active': datetime.now().date(),
        'total_messages': 0, 'voice_messages': 0, 'photos_sent': 0
    })
    
    today = datetime.now().date()
    if user['last_active'] != today:
        streak_broken = (today - user['last_active']).days > 1
        user['daily_streak'] = 0 if streak_broken else user['daily_streak'] + 1
        user['last_active'] = today
        user['xp'] += user_data['ranking']['settings']['daily_bonus']
        for days, bonus in user_data['ranking']['settings']['streak_bonus'].items():
            if user['daily_streak'] >= days:
                user['xp'] += bonus
    
    user['total_messages'] += 1
    user['xp'] += min(3, max(1, len((update.message.text or "").split())))
    
    xp_needed = user['level'] * user_data['ranking']['settings']['xp_per_level']
    if user['xp'] >= xp_needed:
        user['level'] += 1
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🎉 {user['name']} leveled up to Level {user['level']}!",
            reply_to_message_id=update.message.message_id
        )
    
    update_leaderboard()

async def rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['ranking_system']:
        await update.message.reply_text("Ranking system is disabled!")
        return

    user_id = update.effective_user.id
    if user_id not in user_data['ranking']['users']:
        await update.message.reply_text("You haven't earned any XP yet! Start chatting to level up! 🚀")
        return
    
    user = user_data['ranking']['users'][user_id].copy()
    user.update({
        'rank': user_data['ranking']['leaderboard_cache'].index(user_id) + 1,
        'settings': user_data['ranking']['settings'],
        'user_id': user_id
    })
    
    try:
        rank_image = rank_generator.create_rank_card(user)
        rank_title = get_rank_title(user['level'])
        next_level = user['level'] + 1 if user['level'] < len(RANK_TITLES) else user['level']
        xp_needed_next = next_level * user_data['ranking']['settings']['xp_per_level']
        xp_to_next = xp_needed_next - user['xp']
        
        caption = (
            f"🏆 {rank_title}\n📊 Level {user['level']} • Rank #{user['rank']}\n"
            f"💫 {user['xp']:,} / {xp_needed_next:,} XP\n"
            f"🎯 {xp_to_next:,} XP to next level\n🔥 {user.get('daily_streak', 0)} day streak"
        )
        
        await update.message.reply_photo(
            photo=rank_image, caption=caption,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Stats", callback_data="show_stats"), 
                 InlineKeyboardButton("🏆 Leaderboard", callback_data="show_leaderboard")],
                [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_rank")]
            ])
        )
        
    except Exception as e:
        logger.error(f"Rank card failed: {e}")
        await send_text_rank(update, user)

async def refresh_rank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id not in user_data['ranking']['users']:
        await query.edit_message_text("No rank data!")
        return
    
    user = user_data['ranking']['users'][user_id].copy()
    user.update({
        'rank': user_data['ranking']['leaderboard_cache'].index(user_id) + 1,
        'settings': user_data['ranking']['settings'],
        'user_id': user_id
    })
    
    try:
        rank_image = rank_generator.create_rank_card(user)
        rank_title = get_rank_title(user['level'])
        next_level = user['level'] + 1 if user['level'] < len(RANK_TITLES) else user['level']
        xp_needed_next = next_level * user_data['ranking']['settings']['xp_per_level']
        xp_to_next = xp_needed_next - user['xp']
        
        caption = f"🏆 {rank_title}\n📊 Level {user['level']} • Rank #{user['rank']}\n💫 {user['xp']:,} / {xp_needed_next:,} XP"
        
        await query.edit_message_media(
            media=InputMediaPhoto(media=rank_image, caption=caption),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Stats", callback_data="show_stats"), 
                 InlineKeyboardButton("🏆 Leaderboard", callback_data="show_leaderboard")],
                [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_rank")]
            ])
        )
    except Exception as e:
        await query.edit_message_text("Error refreshing rank!")

async def send_text_rank(update: Update, user_data: dict):
    user = user_data
    rank_title = get_rank_title(user['level'])
    next_level = user['level'] + 1 if user['level'] < len(RANK_TITLES) else user['level']
    xp_needed_next = next_level * user_data['ranking']['settings']['xp_per_level']
    xp_to_next = xp_needed_next - user['xp']
    progress = min(100, int((user['xp'] % user_data['ranking']['settings']['xp_per_level']) / 
               user_data['ranking']['settings']['xp_per_level'] * 100))
    
    text_response = (
        f"🏆 <b>{user['name']}</b> (@{user['username']})\n\n{rank_title}\n"
        f"📊 LEVEL {user['level']} • RANK #{user['rank']}\n\n"
        f"💫 XP: {user['xp']:,} / {xp_needed_next:,}\n{generate_progress_bar(progress)} {progress}%\n\n"
        f"🎯 Need {xp_to_next:,} XP for next level\n🔥 Streak: {user.get('daily_streak', 0)} days"
    )
    
    if isinstance(update, Update):
        await update.message.reply_html(text_response)
    else:
        await update.edit_message_text(text_response, parse_mode='HTML')

async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    leaderboard = []
    for idx, user_id in enumerate(user_data['ranking']['leaderboard_cache'][:10], 1):
        u = user_data['ranking']['users'][user_id]
        leaderboard.append(f"{idx}. {u['name']} (@{u['username']}) - Level {u['level']} ({u['xp']} XP)")
    
    await query.edit_message_text(
        text="🏆 <b>TOP 10 USERS</b> 🏆\n\n" + "\n".join(leaderboard),
        parse_mode='HTML', reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 My Rank", callback_data="show_my_rank")]
        ])
    )

async def show_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id not in user_data['ranking']['users']:
        await query.edit_message_text("No stats available!")
        return
    
    user = user_data['ranking']['users'][user_id]
    total_xp = user['xp']
    level = user['level']
    messages = user.get('total_messages', 0)
    voice_messages = user.get('voice_messages', 0)
    photos = user.get('photos_sent', 0)
    streak = user.get('daily_streak', 0)
    
    stats_text = (
        f"📊 <b>Statistics</b>\n\n👤 {user['name']} (@{user['username']})\n"
        f"🏆 {get_rank_title(level)} (Level {level})\n\n💫 <b>XP</b>\n• Total: {total_xp:,}\n"
        f"• To Next: {level * user_data['ranking']['settings']['xp_per_level'] - total_xp}\n\n"
        f"💬 <b>Activity</b>\n• Messages: {messages:,}\n• Voice: {voice_messages}\n"
        f"• Photos: {photos}\n• Streak: {streak} days 🔥\n\n"
        f"📈 <b>Ranking</b>\n• Global: #{user_data['ranking']['leaderboard_cache'].index(user_id) + 1}"
    )
    
    await query.edit_message_text(
        text=stats_text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="show_my_rank")]
        ])
    )

# ========== MESSAGE COUNTING ========== #
async def count_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['message_counter']:
        return
        
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if update.message.text and update.message.text.startswith('/'):
        return
    
    if chat_id not in user_data['message_counts']:
        user_data['message_counts'][chat_id] = {}
    
    user_data['message_counts'][chat_id][user_id] = user_data['message_counts'][chat_id].get(user_id, 0) + 1

async def message_count_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    counts = user_data['message_counts'].get(chat_id, {})
    user_count = counts.get(user_id, 0)
    top_users = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    response = [f"📊 Your messages: {user_count}", "\n🏆 Top chatters:"]
    for idx, (uid, count) in enumerate(top_users, 1):
        try:
            user = await context.bot.get_chat_member(chat_id, uid)
            response.append(f"{idx}. {user.user.first_name}: {count}")
        except: continue
    
    await update.message.reply_text("\n".join(response))

# ========== TRUTH OR DARE ========== #
async def truth_or_dare_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['truth_or_dare']:
        await update.message.reply_text("Truth or Dare disabled!")
        return

    chat_id = update.effective_chat.id
    user_data['truth_or_dare']['active_players'][chat_id] = []
    await update.message.reply_text("🎮 Truth or Dare started! Use /tod_join to join!")

async def join_tod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if chat_id not in user_data['truth_or_dare']['active_players']:
        await update.message.reply_text("❌ No active game. Start with /truthordare")
        return
    
    if user_id not in user_data['truth_or_dare']['active_players'][chat_id]:
        user_data['truth_or_dare']['active_players'][chat_id].append(user_id)
        await update.message.reply_text(f"✅ {update.effective_user.first_name} joined!")
    else:
        await update.message.reply_text("⚠️ Already in game")

async def get_truth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _get_tod_item(update, context, 'truth')

async def get_dare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _get_tod_item(update, context, 'dare')

async def _get_tod_item(update: Update, context: ContextTypes.DEFAULT_TYPE, item_type: str):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if (chat_id not in user_data['truth_or_dare']['active_players'] or 
        user_id not in user_data['truth_or_dare']['active_players'][chat_id]):
        await update.message.reply_text("❌ Join first with /tod_join")
        return
    
    items = user_data['truth_or_dare'][f"{item_type}s"]
    selected = random.choice(items)
    await update.message.reply_text(f"🔮 {update.effective_user.first_name}, your {item_type}:\n\n{selected}")

# ========== WORD GAME ========== #
async def start_word_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['word_games']:
        await update.message.reply_text("Word games disabled!")
        return

    chat_id = update.effective_chat.id
    category_filter = context.args[0].lower() if context.args else None
    available_words = user_data['word_games']['word_bank']
    
    if category_filter:
        available_words = [w for w in available_words if w['category'] == category_filter]
        if not available_words:
            categories = ", ".join(user_data['word_games']['categories'])
            await update.message.reply_text(f"❌ No words in '{category_filter}'\nAvailable: {categories}")
            return
    
    word_data = random.choice(available_words)
    user_data['word_games']['active_games'][chat_id] = {
        'word': word_data['word'].lower(), 'hint': word_data['hint'],
        'category': word_data['category'], 'attempts': 0, 'hints_used': 0, 'max_hints': 3
    }
    
    scrambled = ''.join(random.sample(word_data['word'], len(word_data['word'])))
    await update.message.reply_text(
        f"🧩 *Word Game Started!*\n\n📁 Category: {word_data['category'].upper()}\n"
        f"🔤 Scrambled: `{scrambled}`\n💡 Hint: {word_data['hint']}\n\n"
        f"Type the correct word!\nUse /hint for hints (3 available)",
        parse_mode='Markdown'
    )

async def word_game_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_data['word_games']['active_games']:
        await update.message.reply_text("❌ No active word game! Start with /wordgame")
        return
    
    game = user_data['word_games']['active_games'][chat_id]
    if game['hints_used'] >= game['max_hints']:
        await update.message.reply_text("❌ No more hints!")
        return
    
    game['hints_used'] += 1
    word = game['word']
    hints = [
        f"📏 Word has {len(word)} letters", f"🔤 Starts with '{word[0]}'",
        f"🏷️ Category: {game['category']}", f"🎯 Letters: {', '.join(sorted(set(word)))}"
    ]
    
    hint = hints[game['hints_used'] - 1] if game['hints_used'] <= len(hints) else f"🔍 Try: {word[0]}{'_' * (len(word)-2)}{word[-1]}"
    await update.message.reply_text(f"💡 Hint #{game['hints_used']}: {hint}")

async def handle_word_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['word_games']:
        return

    chat_id = update.effective_chat.id
    guess = update.message.text.strip().lower()
    
    if chat_id not in user_data['word_games']['active_games']:
        return
    
    game = user_data['word_games']['active_games'][chat_id]
    game['attempts'] += 1
    
    if guess == game['word']:
        await update.message.reply_text(f"🎉 Correct! The word was *{game['word']}*\nSolved in {game['attempts']} attempts!", parse_mode='Markdown')
        del user_data['word_games']['active_games'][chat_id]
    else:
        await update.message.reply_text(f"❌ Not quite. Try again!\nHint: {game['hint']}")

# ========== FEATURE CONTROL ========== #
async def enable_feature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Admins only")
        return
    
    if not context.args:
        features = "\n".join(user_data['enabled_features'].keys())
        await update.message.reply_text(f"Usage: /enable <feature>\nAvailable:\n{features}")
        return
    
    feature = context.args[0].lower()
    if feature in user_data['enabled_features']:
        user_data['enabled_features'][feature] = True
        await update.message.reply_text(f"✅ '{feature}' enabled")
    else:
        await update.message.reply_text("❌ Unknown feature")

async def disable_feature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Admins only")
        return
    
    if not context.args:
        features = "\n".join(user_data['enabled_features'].keys())
        await update.message.reply_text(f"Usage: /disable <feature>\nAvailable:\n{features}")
        return
    
    feature = context.args[0].lower()
    if feature in user_data['enabled_features']:
        user_data['enabled_features'][feature] = False
        await update.message.reply_text(f"❌ '{feature}' disabled")
    else:
        await update.message.reply_text("❌ Unknown feature")

async def list_features(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feature_lines = []
    for name, status in user_data['enabled_features'].items():
        status_emoji = '✅' if status else '❌'
        feature_lines.append(f"{status_emoji} {name}")
    
    await update.message.reply_text("🛠️ Features:\n" + "\n".join(feature_lines))

# ========== DOMAIN MANAGEMENT ========== #
async def block_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Admins only")
        return
    
    if not context.args:
        blocked = "\n".join(user_data['link_protection']['blocked_domains']) or "None"
        await update.message.reply_text(f"Blocked domains:\n{blocked}\nUsage: /blockdomain example.com")
        return
    
    domain = clean_domain(context.args[0])
    if domain in user_data['link_protection']['blocked_domains']:
        await update.message.reply_text(f"ℹ️ {domain} already blocked")
    else:
        user_data['link_protection']['blocked_domains'].append(domain)
        await update.message.reply_text(f"✅ Added {domain} to blocked list")

async def unblock_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Admins only")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /unblockdomain example.com")
        return
    
    domain = clean_domain(context.args[0])
    if domain in user_data['link_protection']['blocked_domains']:
        user_data['link_protection']['blocked_domains'].remove(domain)
        await update.message.reply_text(f"✅ Removed {domain} from blocked list")
    else:
        await update.message.reply_text(f"ℹ️ {domain} wasn't blocked")

async def set_link_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Admins only")
        return
    
    if not context.args:
        modes = "\n".join(["strict", "whitelist", "blacklist"])
        await update.message.reply_text(f"Current: {user_data['link_protection']['mode']}\nModes: {modes}")
        return
    
    mode = context.args[0].lower()
    if mode in ["strict", "whitelist", "blacklist"]:
        user_data['link_protection']['mode'] = mode
        await update.message.reply_text(f"✅ Link mode: {mode}")
    else:
        await update.message.reply_text("❌ Invalid mode")

async def list_domains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Admins only")
        return
    
    allowed = "\n".join(user_data['link_protection']['allowed_domains']) or "None"
    blocked = "\n".join(user_data['link_protection']['blocked_domains']) or "None"
    
    await update.message.reply_text(
        f"🛡️ Domains:\n=== Allowed ===\n{allowed}\n\n=== Blocked ===\n{blocked}\n\n"
        f"Mode: {user_data['link_protection']['mode'].upper()}"
    )

async def add_allowed_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Admins only")
        return

    if not context.args:
        domains = "\n".join(user_data['link_protection']['allowed_domains']) or "None"
        await update.message.reply_text(f"Allowed domains:\n{domains}\nUsage: /allowdomain example.com")
        return

    domain = clean_domain(context.args[0])
    if domain in user_data['link_protection']['allowed_domains']:
        await update.message.reply_text(f"ℹ️ {domain} already allowed")
    else:
        user_data['link_protection']['allowed_domains'].append(domain)
        await update.message.reply_text(f"✅ Added {domain} to allowed list")

# ========== WARNING SYSTEM ========== #
async def warnings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    key = f"{chat_id}_{user_id}"
    warnings = user_data['warnings'].get(key, 0)
    
    await update.message.reply_text(
        f"⚠️ You have {warnings}/{WARN_LIMIT} warnings\n"
        f"{'You will be banned on the next warning!' if warnings >= WARN_LIMIT - 1 else ''}"
    )

async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['report_system']:
        await update.message.reply_text("❌ Report system disabled")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /report @username reason")
        return
    
    admins = await update.effective_chat.get_administrators()
    admin_mentions = " ".join([f"@{admin.user.username}" for admin in admins if admin.user.username])
    report_text = " ".join(context.args)
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🚨 REPORT from {update.effective_user.first_name}\n{report_text}\n\n{admin_mentions}"
    )
    await update.message.reply_text("✅ Report sent to admins")

# ========== WELCOME/GOODBYE SYSTEM ========== #
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Admins only")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /setwelcome <message>\nVariables: {name}, {username}, {chat}")
        return
    
    user_data['welcome_message'] = " ".join(context.args)
    await update.message.reply_text("✅ Welcome message updated!")

async def set_goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Admins only")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /setgoodbye <message>\nVariables: {name}, {username}, {chat}")
        return
    
    user_data['goodbye_message'] = " ".join(context.args)
    await update.message.reply_text("✅ Goodbye message updated!")

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['welcome_message']:
        return
    
    for member in update.message.new_chat_members:
        welcome_text = user_data['welcome_message'].format(
            name=member.first_name, username=member.username or "user", chat=update.effective_chat.title
        )
        await update.message.reply_text(welcome_text)

async def goodbye_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['goodbye_message']:
        return
    
    for member in update.message.left_chat_members:
        goodbye_text = user_data['goodbye_message'].format(
            name=member.first_name, username=member.username or "user", chat=update.effective_chat.title
        )
        await update.message.reply_text(goodbye_text)

# ========== MEME SYSTEM ========== #
async def meme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['meme']:
        await update.message.reply_text("❌ Memes disabled!")
        return
    
    enabled_categories = user_data['meme_categories']['enabled']
    if not enabled_categories:
        await update.message.reply_text("❌ No meme categories enabled!")
        return
    
    category = random.choice(enabled_categories)
    if category in MEME_DATABASE and MEME_DATABASE[category]:
        meme_url = random.choice(MEME_DATABASE[category])
        await update.message.reply_photo(photo=meme_url, caption=f"Here's your {category} meme! 😄")
    else:
        await update.message.reply_text("❌ No memes available!")

async def meme_category_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['meme']:
        await update.message.reply_text("❌ Memes disabled!")
        return
    
    if not context.args:
        categories = ", ".join(user_data['meme_categories']['enabled'])
        await update.message.reply_text(f"Usage: /memecategory <category>\nAvailable: {categories}")
        return
    
    category = context.args[0].lower()
    if category not in MEME_DATABASE:
        await update.message.reply_text("❌ Invalid category! Use /memecategories")
        return
    
    if category not in user_data['meme_categories']['enabled']:
        await update.message.reply_text("❌ Category disabled!")
        return
    
    if MEME_DATABASE[category]:
        meme_url = random.choice(MEME_DATABASE[category])
        await update.message.reply_photo(photo=meme_url, caption=f"Here's your {category} meme! 🎭")
    else:
        await update.message.reply_text("❌ No memes in this category!")

async def meme_categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_categories = list(MEME_DATABASE.keys())
    enabled_categories = user_data['meme_categories']['enabled']
    
    response = ["🎭 Meme Categories:\n\n✅ Enabled:"]
    for cat in enabled_categories:
        response.append(f"• {cat} ({len(MEME_DATABASE.get(cat, []))} memes)")
    
    response.append("\n❌ Disabled:")
    for cat in [c for c in all_categories if c not in enabled_categories]:
        response.append(f"• {cat} ({len(MEME_DATABASE.get(cat, []))} memes)")
    
    response.append("\n\nUse /memecategory <category> for specific memes")
    await update.message.reply_text("\n".join(response))

# ========== VIDEO SYSTEM ========== #
async def video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['video']:
        await update.message.reply_text("❌ Videos disabled!")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /video [360|720|1080|4k]\nExample: /video 720")
        return
    
    quality = context.args[0].lower()
    if quality not in ["360", "720", "1080", "4k"]:
        await update.message.reply_text("❌ Invalid quality. Use: 360, 720, 1080, or 4k")
        return
    
    if quality in VIDEO_DATABASE:
        selected = random.choice(VIDEO_DATABASE[quality])
        try:
            await update.message.reply_video(
                video=selected["url"], caption=f"{selected['caption']} (Quality: {quality})", supports_streaming=True
            )
        except Exception as e:
            logger.error(f"Video failed: {str(e)}")
            await update.message.reply_text(f"❌ Couldn't send {quality} video.")
    else:
        await update.message.reply_text("❌ Video not available")

async def short_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        categories = ", ".join(SHORT_VIDEOS.keys())
        await update.message.reply_text(f"🎬 Categories: {categories}\nUsage: /shortvideo <category>")
        return
    
    category = context.args[0].lower()
    if category not in SHORT_VIDEOS:
        await update.message.reply_text(f"❌ Category not found! Available: {', '.join(SHORT_VIDEOS.keys())}")
        return
    
    video_data = random.choice(SHORT_VIDEOS[category])
    try:
        await update.message.reply_video(
            video=video_data["url"], caption=f"🎬 {video_data['caption']} | {category}", supports_streaming=True
        )
    except Exception as e:
        await update.message.reply_text("❌ Couldn't send short video.")

# ========== CUSTOM RESPONSES ========== #
async def add_custom_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Admins only")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text('Usage: /addresponse "pattern" "response1" "response2" ...')
        return
    
    text = " ".join(context.args)
    parts = re.findall(r'"([^"]*)"', text)
    
    if len(parts) < 2:
        await update.message.reply_text("Need pattern and at least one response!")
        return
    
    pattern = parts[0]
    responses = parts[1:]
    user_data['auto_responses']['patterns'][pattern] = responses
    await update.message.reply_text(f"✅ Added response for: {pattern}")

async def handle_auto_responses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['custom_responses']:
        return
    
    message = update.message.text
    if not message: return
    
    user_name = update.effective_user.first_name
    for pattern, responses in user_data['auto_responses']['patterns'].items():
        if re.search(pattern, message, re.IGNORECASE):
            response = random.choice(responses).format(name=user_name)
            await update.message.reply_text(response)
            return
    
    greetings = ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"]
    if any(greet in message.lower() for greet in greetings):
        if user_data['custom_responses']['greetings']:
            response = random.choice(user_data['custom_responses']['greetings']).format(name=user_name)
            await update.message.reply_text(response)
    
    farewells = ["bye", "goodbye", "see you", "take care"]
    if any(farewell in message.lower() for farewell in farewells):
        if user_data['custom_responses']['farewells']:
            response = random.choice(user_data['custom_responses']['farewells']).format(name=user_name)
            await update.message.reply_text(response)
    
    thanks = ["thank you", "thanks", "thx"]
    if any(thank in message.lower() for thank in thanks):
        if user_data['custom_responses']['thanks']:
            response = random.choice(user_data['custom_responses']['thanks']).format(name=user_name)
            await update.message.reply_text(response)

# ========== MODERATION ========== #
async def anti_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['anti_spam']: return
    message = update.message
    if not message.text: return
    if await is_admin(update): return
    
    if re.search(r'(.)\1{10,}', message.text):
        try:
            await message.delete()
            await update.message.reply_text(f"⚠️ {update.effective_user.first_name}, no spam!")
        except Exception as e:
            logger.error(f"Anti-spam failed: {e}")

async def keyword_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['keyword_filter']: return
    message = update.message
    if not message.text: return
    if await is_admin(update): return
    
    text_lower = message.text.lower()
    for banned_word in user_data['banned_words']:
        if banned_word.lower() in text_lower:
            try:
                await message.delete()
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"⚠️ {update.effective_user.first_name}: inappropriate content"
                )
                return
            except Exception as e:
                logger.error(f"Keyword filter failed: {e}")

async def flood_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['flood_control']: return
    if await is_admin(update): return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if chat_id not in user_data['flood']:
        user_data['flood'][chat_id] = {}
    
    now = datetime.now()
    if user_id not in user_data['flood'][chat_id]:
        user_data['flood'][chat_id][user_id] = []
    
    user_data['flood'][chat_id][user_id].append(now)
    user_data['flood'][chat_id][user_id] = [
        ts for ts in user_data['flood'][chat_id][user_id] if (now - ts).total_seconds() <= FLOOD_WINDOW
    ]
    
    if len(user_data['flood'][chat_id][user_id]) > FLOOD_LIMIT:
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id, user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now() + timedelta(minutes=5)
            )
            await context.bot.send_message(
                chat_id=chat_id, text=f"⚠️ {update.effective_user.first_name} muted for 5 minutes (flooding)"
            )
            user_data['flood'][chat_id][user_id] = []
        except Exception as e:
            logger.error(f"Flood control failed: {e}")

async def anti_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['anti_link']: return
    message = update.effective_message
    if not message.text: return
    if await is_admin(update): return
    
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    urls = re.findall(url_pattern, message.text)
    if not urls: return
    
    link_config = user_data['link_protection']
    should_delete = False
    reason = ""
    
    for url in urls:
        domain = clean_domain(url)
        
        if link_config['advanced']['block_shorteners'] and is_shortener(domain):
            should_delete = True; reason = "URL shorteners not allowed"; break
        if link_config['advanced']['block_obfuscated'] and is_obfuscated(domain):
            should_delete = True; reason = "Suspicious link"; break
        
        if link_config['mode'] == "strict":
            should_delete = True; reason = "All links blocked"; break
        elif link_config['mode'] == "whitelist":
            if not any(allowed in domain for allowed in link_config['allowed_domains']):
                should_delete = True; reason = f"Domain not whitelisted: {domain}"; break
        elif link_config['mode'] == "blacklist":
            if any(blocked in domain for blocked in link_config['blocked_domains']):
                should_delete = True; reason = f"Blocked domain: {domain}"; break
    
    if should_delete:
        try:
            await message.delete()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ Link removed from {update.effective_user.first_name}\nReason: {reason}"
            )
        except Exception as e:
            logger.error(f"Failed to delete link: {e}")

# ========== FUN COMMANDS ========== #
async def emoji_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features'].get('random_emoji', True):
        await update.message.reply_text("❌ Emoji feature disabled!")
        return

    emoji_categories = {
        'faces': ['😀', '😃', '😄', '😁', '😆', '😅', '😂', '🤣', '😊', '😇'],
        'animals': ['🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐨', '🐯'],
        'food': ['🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍈', '🍒']
    }

    combinations = [
        f"{random.choice(emoji_categories['faces'])} {random.choice(emoji_categories['animals'])}",
        f"{random.choice(emoji_categories['food'])} {random.choice(emoji_categories['faces'])}",
        f"{random.choice(emoji_categories['animals'])} loves {random.choice(emoji_categories['food'])}",
    ]

    await update.message.reply_text(random.choice(combinations))

async def greet_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_data['enabled_features']['greet_users']: return
    greetings = ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"]
    message = update.message.text.lower()
    
    if any(greet in message for greet in greetings):
        responses = [f"Hello {update.effective_user.first_name}! 👋", "Hi there!", "Hey! How are you?"]
        await update.message.reply_text(random.choice(responses))

async def poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text('Usage: /poll "Question" "Option1" "Option2" ...')
        return
    
    text = " ".join(context.args)
    parts = re.findall(r'"([^"]*)"', text)
    
    if len(parts) < 3:
        await update.message.reply_text("Need question and 2 options!")
        return
    
    question = parts[0]
    options = parts[1:]
    await context.bot.send_poll(chat_id=update.effective_chat.id, question=question, options=options, is_anonymous=False)

# ========== COMMAND LIST ========== #
async def show_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin_user = await is_admin(update)
    
    categories = {
        '🛡️ Moderation': ['warnings', 'report'],
        '🎮 Games': ['truthordare', 'tod_join', 'truth', 'dare', 'wordgame', 'rank'],
        '🎉 Fun': ['meme', 'memecategory', 'memecategories', 'video', 'shortvideo', 'emoji', 'poll'],
        'ℹ️ Utility': ['mcount', 'features', 'commands']
    }
    
    if is_admin_user:
        categories['⚙️ Admin'] = [
            'enable', 'disable', 'blockdomain', 'unblockdomain', 'setlinkmode', 
            'domainlist', 'allowdomain', 'setwelcome', 'setgoodbye', 'addresponse'
        ]

    response = ["<b>📜 Available Commands</b>\n"]
    for category, commands in categories.items():
        response.append(f"\n<b>{category}</b>")
        for cmd in sorted(commands):
            response.append(f"• /{cmd}")
    
    await update.message.reply_html('\n'.join(response))

# ========== MAIN BOT SETUP ========== #
def setup_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_leaderboard, 'interval', hours=1)
    scheduler.start()

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Feature control
    application.add_handler(CommandHandler("enable", enable_feature))
    application.add_handler(CommandHandler("disable", disable_feature))
    application.add_handler(CommandHandler("features", list_features))
    
    # Domain management
    application.add_handler(CommandHandler("blockdomain", block_domain))
    application.add_handler(CommandHandler("unblockdomain", unblock_domain))
    application.add_handler(CommandHandler("setlinkmode", set_link_mode))
    application.add_handler(CommandHandler("domainlist", list_domains))
    application.add_handler(CommandHandler("allowdomain", add_allowed_domain))
    
    # Message counting
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, count_message))
    application.add_handler(CommandHandler("mcount", message_count_command))
    
    # Moderation
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_spam))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_filter))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, flood_control))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_link))
    application.add_handler(CommandHandler("warnings", warnings_command))
    application.add_handler(CommandHandler("report", report_user))
    
    # Welcome/Goodbye
    application.add_handler(CommandHandler("setwelcome", set_welcome))
    application.add_handler(CommandHandler("setgoodbye", set_goodbye))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye_member))
    
    # Custom responses
    application.add_handler(CommandHandler("addresponse", add_custom_response))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auto_responses))
    
    # Utility
    application.add_handler(CommandHandler("poll", poll_command))
    application.add_handler(CommandHandler("commands", show_commands))
    
    # Fun commands
    application.add_handler(CommandHandler("meme", meme_command))
    application.add_handler(CommandHandler("memecategory", meme_category_command))
    application.add_handler(CommandHandler("memecategories", meme_categories_command))
    application.add_handler(CommandHandler("video", video_command))
    application.add_handler(CommandHandler("shortvideo", short_video_command))
    application.add_handler(CommandHandler("emoji", emoji_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, greet_users))
    
    # Ranking system
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ranking))
    application.add_handler(CommandHandler("rank", rank_command))
    application.add_handler(CallbackQueryHandler(leaderboard_callback, pattern="^show_leaderboard$"))
    application.add_handler(CallbackQueryHandler(show_user_stats, pattern="^show_stats$"))
    application.add_handler(CallbackQueryHandler(refresh_rank_callback, pattern="^refresh_rank$"))
    application.add_handler(CallbackQueryHandler(rank_command, pattern="^show_my_rank$"))
    
    # Games
    application.add_handler(CommandHandler("truthordare", truth_or_dare_start))
    application.add_handler(CommandHandler("tod_join", join_tod))
    application.add_handler(CommandHandler("truth", get_truth))
    application.add_handler(CommandHandler("dare", get_dare))
    application.add_handler(CommandHandler("wordgame", start_word_game))
    application.add_handler(CommandHandler("hint", word_game_hint))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_word_guess))
    
    # Start command
    application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text(
        "🤖 Advanced Telegram Bot is running!\nUse /commands to see available commands\nUse /rank to check your level!"
    )))
    
    setup_scheduler()
    logger.info("Bot started with ALL features!")
    application.run_polling()

if __name__ == "__main__":
    main()
