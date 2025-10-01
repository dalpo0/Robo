# Overview

This is a Telegram bot moderation system built with Python that provides comprehensive chat management features. The bot helps administrators maintain order in Telegram groups through automated moderation, spam prevention, user warnings, and interactive features like welcome messages and memes.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Bot Framework
- **Technology**: Python Telegram Bot (PTB) library with `telegram.ext` for handling updates and commands
- **Rationale**: PTB provides a high-level abstraction for Telegram Bot API, simplifying command handling, callback queries, and message processing
- **Event-driven architecture**: Uses handlers (CommandHandler, MessageHandler, CallbackQueryHandler) to respond to different types of user interactions

## Scheduling System
- **Technology**: APScheduler (BackgroundScheduler)
- **Purpose**: Manages time-based operations like temporary mutes, scheduled announcements, and automatic cleanup tasks
- **Rationale**: Enables asynchronous scheduling without blocking the main bot thread

## Data Storage
- **Current approach**: In-memory Python dictionaries for session data
- **Data tracked**:
  - User warnings (per chat)
  - Flood detection metrics (message counts and timestamps)
  - Chat-specific configurations (welcome messages, banned words)
  - Feature toggles (enable/disable specific moderation features)
- **Limitation**: Data is not persistent across bot restarts; suitable for lightweight deployments
- **Future consideration**: Could be migrated to a database (SQLite, PostgreSQL) for persistence

## Moderation Features
- **Warning system**: Tracks user infractions with configurable thresholds (default: 3 warnings)
- **Flood control**: Prevents spam by limiting messages per time window (5 messages per 10 seconds)
- **Keyword filtering**: Blocks messages containing banned words
- **Anti-link protection**: Can filter out URLs to prevent spam links
- **Auto-mute**: Automatically restricts users based on violations
- **Report system**: Allows users to flag problematic content to administrators

## Feature Toggle System
- **Design pattern**: Dictionary-based feature flags (`enabled_features`)
- **Benefits**: Administrators can enable/disable bot functionalities per chat without code changes
- **Configurable features**: Anti-spam, auto-mute, keyword filter, flood control, welcome messages, meme generation, video handling, greeting system, anti-link, reporting, message counting, random emoji

## Authentication & Authorization
- **Admin verification**: Bot checks user permissions before executing administrative commands
- **Telegram native permissions**: Leverages Telegram's built-in admin roles and `ChatPermissions` for restricting users
- **No external authentication**: Relies entirely on Telegram's user management system

# External Dependencies

## Telegram Bot API
- **Library**: `python-telegram-bot`
- **Purpose**: Core bot functionality, message handling, and user interaction
- **Key components used**:
  - `telegram.Update` and `telegram.ext.ContextTypes` for processing updates
  - `ChatPermissions` for managing user restrictions
  - `InlineKeyboardButton` and `InlineKeyboardMarkup` for interactive menus

## APScheduler
- **Purpose**: Background task scheduling for timed moderation actions
- **Use cases**: Unmuting users after timeout periods, scheduling announcements

## Environment Variables
- **BOT_TOKEN**: Telegram bot authentication token (stored in environment for security)
- **Default fallback**: "YOUR_BOT_TOKEN" placeholder for development

## Standard Library Dependencies
- `re`: Regular expressions for pattern matching (URL detection, keyword filtering)
- `random`: Generating random responses (memes, emojis)
- `json`: Configuration data serialization (if persistence is added)
- `logging`: Structured logging for debugging and monitoring
- `datetime`: Timestamp tracking for flood control and scheduled actions

## No Database Currently
- The application currently uses in-memory storage
- No database driver or ORM is implemented
- Consider adding Drizzle ORM with PostgreSQL for production deployments requiring data persistence