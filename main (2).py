import re
import random
import json
import logging
import os
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
WARN_LIMIT = 3
FLOOD_LIMIT = 5  # messages
FLOOD_WINDOW = 10  # seconds

# Data storage
user_data = {
    'warnings': {},
    'flood': {},
    'message_counts': {},
    'welcome_message': "Welcome {name} (@{username}) to {chat}!",
    'banned_words': ["badword1", "badword2"],
    'enabled_features': {
        'anti_spam': True,
        'auto_mute': True,
        'keyword_filter': True,
        'flood_control': True,
        'welcome_message': True,
        'meme': True,
        'video': True,
        'greet_users': True,
        'anti_link': True,
        'report_system': True,
        'message_counter': True,
        'random_emoji': True,
        'ranking_system': True,
        'truth_or_dare': True,
        'word_games': True
    },
    'truth_or_dare': {
        'truths': [
            "What's your most embarrassing moment?",
            "Have you ever cheated in an exam?",
            "What's the weirdest thing you've ever eaten?"
        ],
        'dares': [
            "Send a voice message singing for 30 seconds",
            "Post a childhood photo in this chat",
            "Text your crush right now and screenshot it"
        ],
        'active_players': {}
    },
    'word_games': {
        'active_games': {},
        'word_bank': [
            {'word': 'algorithm', 'hint': 'A step-by-step procedure for calculations'},
            {'word': 'blockchain', 'hint': 'Decentralized digital ledger technology'},
            {'word': 'nebulous', 'hint': 'Vague or ill-defined'}
        ]
    },
    'ranking': {
        'users': {},
        'settings': {
            'xp_per_level': 300,
            'daily_bonus': 50,
            'streak_bonus': {3: 100, 7: 300}
        },
        'leaderboard_cache': [],
        'last_update': None
    },
    'link_protection': {
        'allowed_domains': ["youtube.com", "telegram.org"],
        'blocked_domains': ["download.com", "malware.site"],
        'mode': "whitelist",
        'advanced': {
            'block_shorteners': True,
            'block_obfuscated': True,
            'allow_subdomains': False
        }
    }
}

COMMAND_DESCRIPTIONS = {
    # Moderation
    'warnings': 'Check your warning count',
    'report': 'Report a user to admins (@username reason)',
    
    # Games
    'truthordare': 'Start Truth or Dare game',
    'tod_join': 'Join active Truth or Dare',
    'truth': 'Get a truth question (must be in game)',
    'dare': 'Get a dare (must be in game)',
    'wordgame': 'Start a word-guessing challenge',
    'rank': 'Show your ranking stats',
    'leaderboard': 'Show top users',
    
    # Admin
    'enable': 'Enable a bot feature (admin)',
    'disable': 'Disable a bot feature (admin)',
    'blockdomain': 'Block a domain (admin)',
    'allowdomain': 'Whitelist a domain (admin)',
    'setlinkmode': 'Change link filter mode (admin)',
    
    # Fun
    'meme': 'Get a random meme',
    'video': 'Get a video (360/720/1080/4k)',
    'emoji': 'Get random emoji combinations',
    'poll': 'Create a poll ("Question" "Opt1" "Opt2")',
    
    # Utility
    'mcount': 'Show your message stats',
    'features': 'List toggleable features',
    'commands': 'Show this help message',
    'domainlist': 'Show allowed/blocked domains (admin)'
}

# ========== UTILITY FUNCTIONS ========== #
async def is_admin(update: Update) -> bool:
    """Check if user is admin"""
    return update.effective_user.id in [
        admin.user.id 
        for admin in await update.effective_chat.get_administrators()
    ]

def clean_domain(url: str) -> str:
    """Extract clean domain from URL"""
    return re.sub(r'^https?://|www\.', '', url.split('/')[0].lower())

def is_obfuscated(domain: str) -> bool:
    """Detect suspicious domain patterns"""
    patterns = [
        r'\d',                     # Numbers in domain (d0wnl0ad)
        r'[^\w.-]',                # Special chars
        r'([a-z])\1{2,}',          # Repeated chars (wwww.example)
    ]
    return any(re.search(p, domain) for p in patterns)

def is_shortener(domain: str) -> bool:
    """Detect common URL shorteners"""
    shorteners = ['bit.ly', 'goo.gl', 't.co', 'tinyurl.com']
    return any(s in domain for s in shorteners)

def update_leaderboard():
    """Update leaderboard rankings"""
    users = user_data['ranking']['users']
    user_data['ranking']['leaderboard_cache'] = sorted(
        users.keys(),
        key=lambda uid: (
            -users[uid]['level'], 
            -users[uid]['xp'],
            users[uid]['last_active']
        )
    )
    user_data['ranking']['last_update'] = datetime.now()

def generate_progress_bar(percentage: int, length: int = 15) -> str:
    """Generate visual progress bar"""
    filled = round(percentage / 100 * length)
    return f"┃{'█' * filled}{'━' * (length - filled)}┃"

def generate_rank_card(user_data: dict) -> str:
    """Generate rank card similar to reference image"""
    progress = min(100, int((user_data['xp'] % user_data['settings']['xp_per_level']) / 
               user_data['settings']['xp_per_level'] * 100))
    
    return (
        f"<b>{user_data['name']}</b>\n"
        f"@{user_data['username']}\n\n"
        f"LEVEL {user_data['level']}\n"
        f"RANK #{user_data['rank']}\n\n"
        f"{user_data['xp']} / {user_data['level'] * user_data['settings']['xp_per_level']} XP\n"
        f"{generate_progress_bar(progress)} {progress}%\n\n"
        f"Daily Streak: {user_data['daily_streak']} 🔥\n\n"
        f"<i>Last active: {datetime.now().strftime('%H:%M')}</i>"
    )

# ========== MESSAGE COUNTING SYSTEM ========== #
async def count_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Count messages from users"""
    if not user_data['enabled_features']['message_counter']:
        return
        
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Skip commands
    if update.message.text and update.message.text.startswith('/'):
        return
    
    # Initialize data structure if not exists
    if chat_id not in user_data['message_counts']:
        user_data['message_counts'][chat_id] = {}
    
    # Increment count
    user_data['message_counts'][chat_id][user_id] = user_data['message_counts'][chat_id].get(user_id, 0) + 1

async def message_count_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show message count (/mcount)"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Get counts for this chat
    counts = user_data['message_counts'].get(chat_id, {})
    
    # Get the requesting user's count
    user_count = counts.get(user_id, 0)
    
    # Get top 5 users in this chat
    top_users = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Prepare response
    response = [f"📊 Your message count: {user_count}", "\n🏆 Top chatters:"]
    
    # Add top users to response
    for idx, (uid, count) in enumerate(top_users, 1):
        try:
            user = await context.bot.get_chat_member(chat_id, uid)
            name = user.user.first_name
            response.append(f"{idx}. {name}: {count}")
        except:
            continue
    
    await update.message.reply_text("\n".join(response))

# ========== RANKING SYSTEM ========== #
async def handle_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Update user ranking stats on message"""
    if not user_data['enabled_features']['ranking_system']:
        return

    user_id = update.effective_user.id
    user = user_data['ranking']['users'].setdefault(user_id, {
        'name': update.effective_user.first_name,
        'username': update.effective_user.username or "",
        'xp': 0,
        'level': 1,
        'daily_streak': 0,
        'last_active': datetime.now().date()
    })
    
    # Check daily streak
    today = datetime.now().date()
    if user['last_active'] != today:
        streak_broken = (today - user['last_active']).days > 1
        user['daily_streak'] = 0 if streak_broken else user['daily_streak'] + 1
        user['last_active'] = today
        
        # Award bonuses
        user['xp'] += user_data['ranking']['settings']['daily_bonus']
        for days, bonus in user_data['ranking']['settings']['streak_bonus'].items():
            if user['daily_streak'] >= days:
                user['xp'] += bonus
    
    # Standard XP gain (1-3 XP per message)
    user['xp'] += min(3, max(1, len((update.message.text or "").split())))
    
    # Level up check
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
    """Show user's rank (/rank)"""
    if not user_data['enabled_features']['ranking_system']:
        await update.message.reply_text("Ranking system is disabled!")
        return

    user_id = update.effective_user.id
    if user_id not in user_data['ranking']['users']:
        await update.message.reply_text("You haven't earned any XP yet!")
        return
    
    user = user_data['ranking']['users'][user_id].copy()
    user.update({
        'rank': user_data['ranking']['leaderboard_cache'].index(user_id) + 1,
        'settings': user_data['ranking']['settings']
    })
    
    await update.message.reply_html(
        generate_rank_card(user),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="show_leaderboard")]
        ])
    )

async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle leaderboard button press"""
    query = update.callback_query
    await query.answer()
    
    leaderboard = []
    for idx, user_id in enumerate(user_data['ranking']['leaderboard_cache'][:10], 1):
        u = user_data['ranking']['users'][user_id]
        leaderboard.append(
            f"{idx}. {u['name']} (@{u['username']}) - "
            f"Level {u['level']} ({u['xp']} XP)"
        )
    
    await query.edit_message_text(
        text="🏆 <b>TOP 10 USERS</b> 🏆\n\n" + "\n".join(leaderboard),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 My Rank", callback_data="show_my_rank")]
        ])
    )

# ========== TRUTH OR DARE GAME ========== #
async def truth_or_dare_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a Truth or Dare session (/truthordare)"""
    if not user_data['enabled_features']['truth_or_dare']:
        await update.message.reply_text("Truth or Dare is disabled!")
        return

    chat_id = update.effective_chat.id
    user_data['truth_or_dare']['active_players'][chat_id] = []
    
    await update.message.reply_text(
        "🎮 Truth or Dare started!\n"
        "Use /tod_join to join the game\n"
        "Then use /truth or /dare when ready"
    )

async def join_tod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Join a game (/tod_join)"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if chat_id not in user_data['truth_or_dare']['active_players']:
        await update.message.reply_text("❌ No active game. Start with /truthordare")
        return
    
    if user_id not in user_data['truth_or_dare']['active_players'][chat_id]:
        user_data['truth_or_dare']['active_players'][chat_id].append(user_id)
        await update.message.reply_text(f"✅ {update.effective_user.first_name} joined the game!")
    else:
        await update.message.reply_text("⚠️ You're already in the game")

async def get_truth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get a truth question (/truth)"""
    await _get_tod_item(update, context, 'truth')

async def get_dare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get a dare (/dare)"""
    await _get_tod_item(update, context, 'dare')

async def _get_tod_item(update: Update, context: ContextTypes.DEFAULT_TYPE, item_type: str):
    """Shared logic for truth/dare"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Check if player is in an active game
    if (chat_id not in user_data['truth_or_dare']['active_players'] or 
        user_id not in user_data['truth_or_dare']['active_players'][chat_id]):
        await update.message.reply_text("❌ Join a game first with /tod_join")
        return
    
    items = user_data['truth_or_dare'][f"{item_type}s"]
    selected = random.choice(items)
    
    await update.message.reply_text(
        f"🔮 {update.effective_user.first_name}, your {item_type}:\n\n"
        f"{selected}\n\n"
        f"React with ✅ when done!"
    )

# ========== WORD GAME ========== #
async def start_word_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a word-guessing game (/wordgame)"""
    if not user_data['enabled_features']['word_games']:
        await update.message.reply_text("Word games are disabled!")
        return

    chat_id = update.effective_chat.id
    word_data = random.choice(user_data['word_games']['word_bank'])
    
    user_data['word_games']['active_games'][chat_id] = {
        'word': word_data['word'].lower(),
        'hint': word_data['hint'],
        'attempts': 0
    }
    
    scrambled = ''.join(random.sample(word_data['word'], len(word_data['word'])))
    
    await update.message.reply_text(
        "🧩 *New Word Game Started!*\n\n"
        f"Scrambled: {scrambled}\n"
        f"Hint: {word_data['hint']}\n\n"
        "Type the correct word in chat!",
        parse_mode='Markdown'
    )

async def handle_word_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process word guesses"""
    if not user_data['enabled_features']['word_games']:
        return

    chat_id = update.effective_chat.id
    guess = update.message.text.strip().lower()
    
    if chat_id not in user_data['word_games']['active_games']:
        return
    
    game = user_data['word_games']['active_games'][chat_id]
    game['attempts'] += 1
    
    if guess == game['word']:
        await update.message.reply_text(
            f"🎉 Correct! The word was *{game['word']}*\n"
            f"Solved in {game['attempts']} attempts!",
            parse_mode='Markdown'
        )
        del user_data['word_games']['active_games'][chat_id]
    else:
        similarity = sum(a==b for a,b in zip(guess, game['word'])) / max(len(guess), len(game['word']))
        
        if similarity > 0.7:
            hint = "Very close! "
        elif similarity > 0.4:
            hint = "Getting warmer. "
        else:
            hint = "Not quite. "
        
        await update.message.reply_text(
            f"❌ {hint}Try again!\n"
            f"Hint: {game['hint']}"
        )

# ========== FEATURE CONTROL SYSTEM ========== #
async def enable_feature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable a bot feature (/enable)"""
    if not await is_admin(update):
        await update.message.reply_text("❌ Only admins can enable features")
        return
    
    if not context.args:
        features = "\n".join(user_data['enabled_features'].keys())
        await update.message.reply_text(f"Usage: /enable <feature>\nAvailable features:\n{features}")
        return
    
    feature = context.args[0].lower()
    if feature in user_data['enabled_features']:
        user_data['enabled_features'][feature] = True
        await update.message.reply_text(f"✅ Feature '{feature}' enabled")
    else:
        await update.message.reply_text(f"❌ Unknown feature. Use /features to list available features")

async def disable_feature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable a bot feature (/disable)"""
    if not await is_admin(update):
        await update.message.reply_text("❌ Only admins can disable features")
        return
    
    if not context.args:
        features = "\n".join(user_data['enabled_features'].keys())
        await update.message.reply_text(f"Usage: /disable <feature>\nAvailable features:\n{features}")
        return
    
    feature = context.args[0].lower()
    if feature in user_data['enabled_features']:
        user_data['enabled_features'][feature] = False
        await update.message.reply_text(f"❌ Feature '{feature}' disabled")
    else:
        await update.message.reply_text(f"❌ Unknown feature. Use /features to list available features")

async def list_features(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all features and their status (/features)"""
    # Create a modified copy of the features dictionary
    features_display = user_data['enabled_features'].copy()
    
    # Replace the simple 'video' key with our detailed description
    features_display['video'] = {
        'status': features_display['video'],
        'description': "/video [360|720|1080|4k|youtube-link]"
    }
    
    # Build the status message
    feature_lines = []
    for name, data in features_display.items():
        if isinstance(data, dict):  # This is our special video entry
            status = '✅' if data['status'] else '❌'
            feature_lines.append(f"{status} video: {data['description']}")
        else:
            status = '✅' if data else '❌'
            feature_lines.append(f"{status} {name}")
    
    await update.message.reply_text(
        "🛠️ Feature Status:\n" + "\n".join(feature_lines) +
        "\n\nAdmins can use /enable or /disable to change"
    )

# ========== DOMAIN MANAGEMENT ========== #
async def block_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add domain to blocklist (/blockdomain)"""
    if not await is_admin(update):
        await update.message.reply_text("❌ Only admins can block domains")
        return
    
    if not context.args:
        blocked = "\n".join(user_data['link_protection']['blocked_domains']) or "None"
        await update.message.reply_text(f"Current blocked domains:\n{blocked}\n\nUsage: /blockdomain example.com")
        return
    
    domain = clean_domain(context.args[0])
    if domain in user_data['link_protection']['blocked_domains']:
        await update.message.reply_text(f"ℹ️ {domain} is already blocked")
    else:
        user_data['link_protection']['blocked_domains'].append(domain)
        await update.message.reply_text(f"✅ Added {domain} to blocked list")

async def unblock_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove domain from blocklist (/unblockdomain)"""
    if not await is_admin(update):
        await update.message.reply_text("❌ Only admins can unblock domains")
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
    """Set link filtering mode (/setlinkmode)"""
    if not await is_admin(update):
        await update.message.reply_text("❌ Only admins can change link mode")
        return
    
    if not context.args:
        modes = "\n".join(["strict", "whitelist", "blacklist"])
        await update.message.reply_text(
            f"Current mode: {user_data['link_protection']['mode']}\n"
            f"Available modes: {modes}\n"
            f"Usage: /setlinkmode <mode>"
        )
        return
    
    mode = context.args[0].lower()
    if mode in ["strict", "whitelist", "blacklist"]:
        user_data['link_protection']['mode'] = mode
        await update.message.reply_text(f"✅ Link mode set to: {mode}")
    else:
        await update.message.reply_text("❌ Invalid mode. Use 'strict', 'whitelist' or 'blacklist'")

async def list_domains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show domain lists (/domainlist)"""
    if not await is_admin(update):
        await update.message.reply_text("❌ Admin only command")
        return
    
    allowed = "\n".join(user_data['link_protection']['allowed_domains']) or "None"
    blocked = "\n".join(user_data['link_protection']['blocked_domains']) or "None"
    
    await update.message.reply_text(
        f"🛡️ Domain Lists:\n=== Allowed ===\n{allowed}\n\n"
        f"=== Blocked ===\n{blocked}\n\n"
        f"Mode: {user_data['link_protection']['mode'].upper()}"
    )

async def add_allowed_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add domain to whitelist (/allowdomain)"""
    if not await is_admin(update):
        await update.message.reply_text("❌ Only admins can modify allowed domains")
        return

    if not context.args:
        domains = "\n".join(user_data['link_protection']['allowed_domains']) or "None"
        await update.message.reply_text(
            f"Current allowed domains:\n{domains}\n\n"
            "Usage: /allowdomain example.com"
        )
        return

    domain = clean_domain(context.args[0])
    if domain in user_data['link_protection']['allowed_domains']:
        await update.message.reply_text(f"ℹ️ {domain} is already allowed")
    else:
        user_data['link_protection']['allowed_domains'].append(domain)
        await update.message.reply_text(f"✅ Added {domain} to allowed list")

# ========== ADVANCED ANTI-LINK ========== #
async def anti_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Advanced link protection system"""
    if not user_data['enabled_features']['anti_link']:
        return
        
    message = update.effective_message
    if not message.text:
        return
    
    # Skip admins
    if await is_admin(update):
        return
    
    # Advanced URL extraction
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    urls = re.findall(url_pattern, message.text)
    
    if not urls:
        return
    
    link_config = user_data['link_protection']
    should_delete = False
    reason = ""
    
    for url in urls:
        domain = clean_domain(url)
        
        # Check shorteners
        if link_config['advanced']['block_shorteners'] and is_shortener(domain):
            should_delete = True
            reason = "URL shorteners are not allowed"
            break
        
        # Check obfuscation
        if link_config['advanced']['block_obfuscated'] and is_obfuscated(domain):
            should_delete = True
            reason = "Suspicious link detected"
            break
        
        # Mode-based filtering
        if link_config['mode'] == "strict":
            should_delete = True
            reason = "All links are blocked"
            break
        elif link_config['mode'] == "whitelist":
            if not any(allowed in domain for allowed in link_config['allowed_domains']):
                should_delete = True
                reason = f"Domain not whitelisted: {domain}"
                break
        elif link_config['mode'] == "blacklist":
            if any(blocked in domain for blocked in link_config['blocked_domains']):
                should_delete = True
                reason = f"Blocked domain: {domain}"
                break
    
    if should_delete:
        try:
            await message.delete()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ Link removed from {update.effective_user.first_name}\nReason: {reason}"
            )
        except Exception as e:
            logger.error(f"Failed to delete link: {e}")

# ========== MODERATION FEATURES ========== #
async def anti_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detect and handle spam messages"""
    if not user_data['enabled_features']['anti_spam']:
        return
        
    message = update.message
    if not message.text:
        return
    
    # Skip admins
    if await is_admin(update):
        return
    
    # Detect repeated characters (spam patterns)
    if re.search(r'(.)\1{10,}', message.text):
        try:
            await message.delete()
            await update.message.reply_text(
                f"⚠️ {update.effective_user.first_name}, please don't spam!"
            )
        except Exception as e:
            logger.error(f"Anti-spam failed: {e}")

async def keyword_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Filter banned words"""
    if not user_data['enabled_features']['keyword_filter']:
        return
        
    message = update.message
    if not message.text:
        return
    
    # Skip admins
    if await is_admin(update):
        return
    
    text_lower = message.text.lower()
    
    for banned_word in user_data['banned_words']:
        if banned_word.lower() in text_lower:
            try:
                await message.delete()
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"⚠️ Message from {update.effective_user.first_name} contained inappropriate content"
                )
                return
            except Exception as e:
                logger.error(f"Keyword filter failed: {e}")

async def flood_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prevent message flooding"""
    if not user_data['enabled_features']['flood_control']:
        return
    
    # Skip admins
    if await is_admin(update):
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Initialize flood tracking
    if chat_id not in user_data['flood']:
        user_data['flood'][chat_id] = {}
    
    now = datetime.now()
    
    # Get user's message history
    if user_id not in user_data['flood'][chat_id]:
        user_data['flood'][chat_id][user_id] = []
    
    # Add current message timestamp
    user_data['flood'][chat_id][user_id].append(now)
    
    # Remove old timestamps (outside the window)
    user_data['flood'][chat_id][user_id] = [
        ts for ts in user_data['flood'][chat_id][user_id]
        if (now - ts).total_seconds() <= FLOOD_WINDOW
    ]
    
    # Check if flooding
    if len(user_data['flood'][chat_id][user_id]) > FLOOD_LIMIT:
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now() + timedelta(minutes=5)
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ {update.effective_user.first_name} has been muted for 5 minutes (flooding)"
            )
            user_data['flood'][chat_id][user_id] = []
        except Exception as e:
            logger.error(f"Flood control failed: {e}")

async def warnings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check warning count (/warnings)"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    key = f"{chat_id}_{user_id}"
    warnings = user_data['warnings'].get(key, 0)
    
    await update.message.reply_text(
        f"⚠️ You have {warnings}/{WARN_LIMIT} warnings\n"
        f"{'You will be banned on the next warning!' if warnings >= WARN_LIMIT - 1 else ''}"
    )

async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Report a user to admins (/report)"""
    if not user_data['enabled_features']['report_system']:
        await update.message.reply_text("❌ Report system is disabled")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /report @username reason")
        return
    
    # Get chat admins
    admins = await update.effective_chat.get_administrators()
    admin_mentions = " ".join([f"@{admin.user.username}" for admin in admins if admin.user.username])
    
    report_text = " ".join(context.args)
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🚨 REPORT from {update.effective_user.first_name}\n{report_text}\n\n{admin_mentions}"
    )
    
    await update.message.reply_text("✅ Report sent to admins")

# ========== UTILITY COMMANDS ========== #
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set custom welcome message (/setwelcome)"""
    if not await is_admin(update):
        await update.message.reply_text("❌ Only admins can set welcome messages")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: /setwelcome <message>\n"
            "Variables: {name}, {username}, {chat}"
        )
        return
    
    user_data['welcome_message'] = " ".join(context.args)
    await update.message.reply_text("✅ Welcome message updated!")

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome new members"""
    if not user_data['enabled_features']['welcome_message']:
        return
    
    for member in update.message.new_chat_members:
        welcome_text = user_data['welcome_message'].format(
            name=member.first_name,
            username=member.username or "user",
            chat=update.effective_chat.title
        )
        await update.message.reply_text(welcome_text)

async def poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a poll (/poll)"""
    if len(context.args) < 3:
        await update.message.reply_text('Usage: /poll "Question" "Option1" "Option2" ...')
        return
    
    # Parse quoted arguments
    text = " ".join(context.args)
    parts = re.findall(r'"([^"]*)"', text)
    
    if len(parts) < 3:
        await update.message.reply_text("Need at least a question and 2 options!")
        return
    
    question = parts[0]
    options = parts[1:]
    
    await context.bot.send_poll(
        chat_id=update.effective_chat.id,
        question=question,
        options=options,
        is_anonymous=False
    )

# ========== FUN COMMANDS ========== #
async def meme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a random meme (/meme)"""
    if not user_data['enabled_features']['meme']:
        await update.message.reply_text("❌ Meme feature is disabled!")
        return
    
    memes = [ 
        "https://i.imgflip.com/30b1gx.jpg",  # Batman slapping Robin
        "https://i.imgflip.com/1bij.jpg",    # Two Buttons
        "https://i.imgflip.com/1g8my4.jpg",  # 10 Guy
        "https://i.imgflip.com/1otk96.jpg",  # Hard To Swallow Pills
        "https://i.imgflip.com/261o3j.jpg",  # Brace Yourselves
        "https://i.imgflip.com/1c1uej.jpg",  # Third World Success
        "https://i.imgflip.com/1h7in3.jpg",  # Roll Safe
        "https://i.imgflip.com/1e7ql7.jpg",  # X, X Everywhere
        "https://i.imgflip.com/1b42wb.jpg",  # First World Problems
        "https://i.imgflip.com/1bim.jpg",    # Philosoraptor
        "https://i.imgflip.com/1bip.jpg",    # Socially Awesome Penguin
        "https://i.imgflip.com/1bix.jpg",    # Joseph Ducreux
        "https://i.imgflip.com/1bgw.jpg",    # The Most Interesting Man
        "https://i.imgflip.com/1bhf.jpg",    # Condescending Wonka
        "https://i.imgflip.com/1bhk.jpg",    # Y U No
        "https://i.imgflip.com/1bh8.jpg",    # Futurama Fry
        "https://i.imgflip.com/1bhm.jpg",    # Bad Luck Brian
        "https://i.imgflip.com/1bhn.jpg",    # Good Guy Greg
        "https://i.imgflip.com/1bh3.jpg",    # College Freshman
        "https://i.imgflip.com/1bh1.jpg",    # Success Kid
        "https://i.imgflip.com/1bh5.jpg",    # The Rock Driving
        "https://i.imgflip.com/1bh6.jpg",    # Scumbag Steve
        "https://i.imgflip.com/1bh7.jpg",    # Insanity Wolf
        "https://i.imgflip.com/1bh9.jpg",    # Annoying Facebook Girl
        "https://i.imgflip.com/1bh0.jpg",    # Ancient Aliens
        "https://i.imgflip.com/1bh2.jpg",    # Grumpy Cat
        "https://i.imgflip.com/1bh4.jpg",    # Unhelpful High School Teacher
        "https://i.imgflip.com/1bha.jpg",    # Overly Attached Girlfriend
        "https://i.imgflip.com/1bhb.jpg",    # Paranoid Parrot
        "https://i.imgflip.com/1bhc.jpg",    # Socially Awkward Penguin"
    
        "https://i.imgflip.com/2h6y5t.jpg",  # Programming vs Real Life
        "https://i.imgflip.com/2/1hl0b5.jpg", # It works on my machine
        "https://i.imgflip.com/2/1hq51n.jpg", # When you finally fix the bug
        "https://i.imgflip.com/2/1hwc5p.jpg", # Code comments be like
        "https://i.imgflip.com/2/1hq5b7.jpg", # Programming socks
        "https://i.imgflip.com/2/1hq5c9.jpg", # Git commit messages
        "https://i.imgflip.com/2/1hq5d1.jpg", # Rubber duck debugging
        "https://i.imgflip.com/2/1hq5e3.jpg", # Stack Overflow saves the day
        "https://i.imgflip.com/2/1hq5f5.jpg", # When the code works first try
        "https://i.imgflip.com/2/1hq5g7.jpg", # Programming in a nutshell
        "https://i.imgflip.com/2/1hq5h9.jpg", # How it started vs how it's going
        "https://i.imgflip.com/2/1hq5i1.jpg", # Technical debt
        "https://i.imgflip.com/2/1hq5j3.jpg", # Code review
        "https://i.imgflip.com/2/1hq5k5.jpg", # Legacy code
        "https://i.imgflip.com/2/1hq5l7.jpg"  # Monday vs Friday code
    
        "https://i.imgflip.com/1o3j1p.jpg",  # Doge
        "https://i.imgflip.com/1o3j2q.jpg",  # Grumpy Cat
        "https://i.imgflip.com/1o3j3r.jpg",  # Cute Cat
        "https://i.imgflip.com/1o3j4s.jpg",  # Happy Dog
        "https://i.imgflip.com/1o3j5t.jpg",  # Confused Puppy
        "https://i.imgflip.com/1o3j6u.jpg",  # Smug Cat
        "https://i.imgflip.com/1o3j7v.jpg",  # Excited Dog
        "https://i.imgflip.com/1o3j8w.jpg",  # Sleepy Cat
        "https://i.imgflip.com/1o3j9x.jpg",  # Playful Puppy
        "https://i.imgflip.com/1o3j0y.jpg"   # Majestic Cat
    
        "https://i.imgflip.com/1o3k1p.jpg",  # Gaming setup
        "https://i.imgflip.com/1o3k2q.jpg",  # When you win
        "https://i.imgflip.com/1o3k3r.jpg",  # When you lose
        "https://i.imgflip.com/1o3k4s.jpg",  # Lag issues
        "https://i.imgflip.com/1o3k5t.jpg",  # Toxic teammates
        "https://i.imgflip.com/1o3k6u.jpg",  # Noob vs Pro
        "https://i.imgflip.com/1o3k7v.jpg",  # Gaming all night
        "https://i.imgflip.com/1o3k8w.jpg",  # Broken controller
        "https://i.imgflip.com/1o3k9x.jpg",  # Achievement unlocked
        "https://i.imgflip.com/1o3k0y.jpg"   # Boss fight
    
        "https://i.imgflip.com/1o3l1p.jpg",  # Surprised Pikachu
        "https://i.imgflip.com/1o3l2q.jpg",  # Mind Blown
        "https://i.imgflip.com/1o3l3r.jpg",  # Facepalm
        "https://i.imgflip.com/1o3l4s.jpg",  # Crying Laughing
        "https://i.imgflip.com/1o3l5t.jpg",  # Angry Face
        "https://i.imgflip.com/1o3l6u.jpg",  # Happy Tears
        "https://i.imgflip.com/1o3l7v.jpg",  # Shocked
        "https://i.imgflip.com/1o3l8w.jpg",  # Confused
        "https://i.imgflip.com/1o3l9x.jpg",  # Excited
        "https://i.imgflip.com/1o3l0y.jpg"   # Disappointed

        "https://i.imgflip.com/1o3m1p.jpg",  # Keep Going
        "https://i.imgflip.com/1o3m2q.jpg",  # You Can Do It
        "https://i.imgflip.com/1o3m3r.jpg",  # Never Give Up
        "https://i.imgflip.com/1o3m4s.jpg",  # Dream Big
        "https://i.imgflip.com/1o3m5t.jpg",  # Success Journey
        "https://i.imgflip.com/1o3m6u.jpg",  # Hard Work Pays
        "https://i.imgflip.com/1o3m7v.jpg",  # Believe in Yourself
        "https://i.imgflip.com/1o3m8w.jpg",  # Growth Mindset
        "https://i.imgflip.com/1o3m9x.jpg",  # Progress Not Perfection
        "https://i.imgflip.com/1o3m0y.jpg"   # Small Steps

        "https://i.imgflip.com/1o3n1p.jpg",  # Old vs New Tech
        "https://i.imgflip.com/1o3n2q.jpg",  # Software Updates
        "https://i.imgflip.com/1o3n3r.jpg",  # Internet Problems
        "https://i.imgflip.com/1o3n4s.jpg",  # Smartphone Addiction
        "https://i.imgflip.com/1o3n5t.jpg",  # Social Media
        "https://i.imgflip.com/1o3n6u.jpg",  # AI Taking Over
        "https://i.imgflip.com/1o3n7v.jpg",  # Cloud Computing
        "https://i.imgflip.com/1o3n8w.jpg",  # Cybersecurity
        "https://i.imgflip.com/1o3n9x.jpg",  # Big Data
        "https://i.imgflip.com/1o3n0y.jpg"   # Internet of Things

        "https://i.imgflip.com/1o3o1p.jpg",  # Monday vs Friday
        "https://i.imgflip.com/1o3o2q.jpg",  # Work From Home
        "https://i.imgflip.com/1o3o3r.jpg",  # Meetings That Could Be Emails
        "https://i.imgflip.com/1o3o4s.jpg",  # Coffee Addiction
        "https://i.imgflip.com/1o3o5t.jpg",  # Deadline Approaching
        "https://i.imgflip.com/1o3o6u.jpg",  # Work-Life Balance
        "https://i.imgflip.com/1o3o7v.jpg",  # Teamwork
        "https://i.imgflip.com/1o3o8w.jpg",  # Productivity
        "https://i.imgflip.com/1o3o9x.jpg",  # Remote Work
        "https://i.imgflip.com/1o3o0y.jpg"   # Office Culture
    
        "https://i.imgflip.com/30b1gx.jpg",
        "https://i.imgflip.com/1bij.jpg",
        "https://i.imgflip.com/1g8my4.jpg"
    ]
    
    await update.message.reply_photo(
        photo=random.choice(memes),
        caption="Here's your meme! 😄"
    )

async def video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send video based on quality (/video)"""
    if not user_data['enabled_features']['video']:
        await update.message.reply_text("❌ Video feature is disabled!")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: /video [360|720|1080|4k]\n"
            "Example: /video 720"
        )
        return
    
    quality = context.args[0].lower()
    
    if quality not in ["360", "720", "1080", "4k"]:
        await update.message.reply_text("❌ Invalid quality. Use: 360, 720, 1080, or 4k")
        return
    
    video_db = {
        "360": [
            {
                "url": "https://sample-videos.com/video123/mp4/360/big_buck_bunny_360p_5mb.mp4",
                "caption": "360p Sample (5MB)",
                "width": 640,
                "height": 360,
                "type": "direct"
            }
        ],
        "720": [
            {
                "url": "https://youtu.be/EAbFyj06mLU?feature",
                "caption": "720p HD Stream",
                "width": 1280,
                "height": 720,
                "type": "streamable"
            }
        ],
        "1080": [
            {
                "url": "https://sample-videos.com/video123/mp4/1080/big_buck_bunny_1080p_50mb.mp4",
                "caption": "1080p Full HD",
                "width": 1920,
                "height": 1080,
                "type": "direct"
            }
        ],
        "4k": [
            {
                "url": "https://example.com/4k-sample.mp4",
                "caption": "4K Ultra HD Demo",
                "width": 3840,
                "height": 2160,
                "type": "direct"
            }
        ]
    }

    selected = random.choice(video_db[quality])
    
    try:
        if selected["type"] == "streamable":
            await update.message.reply_video(
                video=f"https://streamable.com/{selected['url']}",
                caption=f"{selected['caption']} (Quality: {quality})",
                width=selected["width"],
                height=selected["height"],
                supports_streaming=True
            )
        else:
            await update.message.reply_video(
                video=selected["url"],
                caption=f"{selected['caption']} (Quality: {quality})",
                width=selected["width"],
                height=selected["height"],
                supports_streaming=True,
                duration=30
            )
    except Exception as e:
        logger.error(f"{quality} video failed: {str(e)}")
        await update.message.reply_text(f"❌ Couldn't send {quality} video.\n📹 Direct link: {selected['url']}")

async def greet_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Respond to greetings"""
    if not user_data['enabled_features']['greet_users']:
        return

    greetings = ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"]
    message = update.message.text.lower()
    
    if any(greet in message for greet in greetings):
        responses = [
            f"Hello {update.effective_user.first_name}! 👋",
            f"Hi there @{update.effective_user.username}!" if update.effective_user.username else "Hi there!",
            "Hey! How are you today?",
            "Greetings! Nice to see you!",
            "Welcome to the chat! 😊"
        ]
        await update.message.reply_text(random.choice(responses))

async def emoji_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send random emoji combinations (/emoji)"""
    if not user_data['enabled_features'].get('random_emoji', True):
        await update.message.reply_text("❌ Random emoji feature is disabled!")
        return

    # Categories of emojis
    emoji_categories = {
        'faces': ['😀', '😃', '😄', '😁', '😆', '😅', '😂', '🤣', '😊', '😇'],
        'animals': ['🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐨', '🐯'],
        'food': ['🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍈', '🍒'],
        'objects': ['⌚', '📱', '💻', '⌨️', '🖥️', '🖨️', '🖱️', '🖲️', '🎮', '🎲'],
        'symbols': ['❤️', '🧡', '💛', '💚', '💙', '💜', '🖤', '🤍', '🤎', '💔']
    }

    # Create random combinations
    combinations = [
        f"{random.choice(emoji_categories['faces'])} {random.choice(emoji_categories['animals'])}",
        f"{random.choice(emoji_categories['food'])} {random.choice(emoji_categories['objects'])}",
        f"{random.choice(emoji_categories['faces'])} {random.choice(emoji_categories['food'])} {random.choice(emoji_categories['symbols'])}",
        f"{random.choice(emoji_categories['animals'])} loves {random.choice(emoji_categories['food'])}",
        f"{random.choice(emoji_categories['symbols'])} {random.choice(emoji_categories['objects'])} {random.choice(emoji_categories['faces'])}",
        f"{random.choice(emoji_categories['faces'] * 3)}",
        f"{random.choice(emoji_categories['animals'])} meets {random.choice(emoji_categories['animals'])}",
        " ".join(random.choice(list(emoji_categories.values())[i]) for i in range(5))
    ]

    # Select and send a random combination
    response = random.choice(combinations)
    await update.message.reply_text(response)

# ========== COMMAND LIST ========== #
async def show_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all available commands (/commands)"""
    is_admin_user = await is_admin(update)
    
    categories = {
        '🛡️ Moderation': ['warnings', 'report'],
        '🎮 Games': ['truthordare', 'tod_join', 'truth', 'dare', 'wordgame', 'rank', 'leaderboard'],
        '🎉 Fun': ['meme', 'video', 'emoji', 'poll'],
        'ℹ️ Utility': ['mcount', 'features', 'commands']
    }
    
    if is_admin_user:
        categories['⚙️ Admin'] = [
            'enable', 'disable', 'blockdomain', 
            'allowdomain', 'setlinkmode', 'domainlist'
        ]

    response = ["<b>📜 Available Commands</b>\n<code>Use /command for details</code>\n"]
    
    for category, commands in categories.items():
        response.append(f"\n<b>{category}</b>")
        for cmd in sorted(commands):
            desc = COMMAND_DESCRIPTIONS.get(cmd, "No description")
            response.append(f"• /{cmd} - {desc}")
    
    await update.message.reply_html('\n'.join(response))

# ========== MAIN BOT SETUP ========== #
def setup_scheduler():
    """Setup background tasks"""
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_leaderboard, 'interval', hours=1)
    scheduler.start()

def main():
    """Start the bot"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Feature control commands
    application.add_handler(CommandHandler("enable", enable_feature))
    application.add_handler(CommandHandler("disable", disable_feature))
    application.add_handler(CommandHandler("features", list_features))
    
    # Domain management commands
    application.add_handler(CommandHandler("blockdomain", block_domain))
    application.add_handler(CommandHandler("unblockdomain", unblock_domain))
    application.add_handler(CommandHandler("setlinkmode", set_link_mode))
    application.add_handler(CommandHandler("domainlist", list_domains))
    application.add_handler(CommandHandler("allowdomain", add_allowed_domain))
    
    # Message counting system
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, count_message))
    application.add_handler(CommandHandler("mcount", message_count_command))
    
    # Moderation handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_spam))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_filter))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, flood_control))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_link))
    application.add_handler(CommandHandler("warnings", warnings_command))
    application.add_handler(CommandHandler("report", report_user))
    
    # Utility handlers
    application.add_handler(CommandHandler("setwelcome", set_welcome))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    application.add_handler(CommandHandler("poll", poll_command))
    application.add_handler(CommandHandler("commands", show_commands))
    
    # Fun handlers
    application.add_handler(CommandHandler("meme", meme_command))
    application.add_handler(CommandHandler("video", video_command))
    application.add_handler(CommandHandler("emoji", emoji_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, greet_users))
    
    # Ranking system
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ranking))
    application.add_handler(CommandHandler("rank", rank_command))
    application.add_handler(CallbackQueryHandler(leaderboard_callback, pattern="^show_leaderboard$"))
    
    # Games
    application.add_handler(CommandHandler("truthordare", truth_or_dare_start))
    application.add_handler(CommandHandler("tod_join", join_tod))
    application.add_handler(CommandHandler("truth", get_truth))
    application.add_handler(CommandHandler("dare", get_dare))
    application.add_handler(CommandHandler("wordgame", start_word_game))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_word_guess))
    
    # Basic commands
    application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text(
        "🤖 Bot is running!\n"
        "Use /features to see available commands\n"
        "Admins can use /enable and /disable to control features"
    )))
    
    setup_scheduler()
    logger.info("Bot started polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
