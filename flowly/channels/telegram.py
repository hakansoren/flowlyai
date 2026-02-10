"""Telegram channel implementation using python-telegram-bot."""

import asyncio
import mimetypes
import re
from pathlib import Path

from loguru import logger
from telegram import Update, InputFile, BotCommand
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

from flowly.bus.events import InboundMessage, OutboundMessage
from flowly.bus.queue import MessageBus
from flowly.channels.base import BaseChannel
from flowly.config.schema import TelegramConfig
from flowly.pairing import upsert_pairing_request, read_allow_from_store


# Supported image MIME types for Telegram photos
TELEGRAM_PHOTO_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Maximum caption length for Telegram
MAX_CAPTION_LENGTH = 1024


def _markdown_to_telegram_html(text: str) -> str:
    """
    Convert markdown to Telegram-safe HTML.
    """
    if not text:
        return ""

    # 1. Extract and protect code blocks (preserve content from other processing)
    code_blocks: list[str] = []
    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)

    # 2. Extract and protect inline code
    inline_codes: list[str] = []
    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # 3. Headers # Title -> just the title text
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

    # 4. Blockquotes > text -> just the text (before HTML escaping)
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)

    # 5. Escape HTML special characters
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Links [text](url) - must be before bold/italic to handle nested cases
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # 7. Bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # 8. Italic _text_ (avoid matching inside words like some_var_name)
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)

    # 9. Strikethrough ~~text~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)

    # 10. Bullet lists - item -> • item
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)

    # 11. Restore inline code with HTML tags
    for i, code in enumerate(inline_codes):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 12. Restore code blocks with HTML tags
    for i, code in enumerate(code_blocks):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    return text


def _is_image_file(path: Path) -> bool:
    """Check if a file is an image that can be sent as a Telegram photo."""
    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type in TELEGRAM_PHOTO_TYPES:
        return True
    # Also check by extension for common cases
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _truncate_caption(text: str, max_length: int = MAX_CAPTION_LENGTH) -> str:
    """Truncate text to fit Telegram's caption limit."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


class TelegramChannel(BaseChannel):
    """
    Telegram channel using long polling.

    Supports:
    - Text messages with markdown formatting
    - Photo/image sending with captions
    - Document sending

    Simple and reliable - no webhook/public IP needed.
    """

    name = "telegram"

    # Native bot commands
    NATIVE_COMMANDS = [
        BotCommand("new", "Start a new conversation"),
        BotCommand("compact", "Summarize conversation history"),
        BotCommand("clear", "Clear session history"),
        BotCommand("help", "Show available commands"),
    ]

    def __init__(self, config: TelegramConfig, bus: MessageBus, groq_api_key: str | None = None):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies
        self._compact_callback: callable | None = None  # Set by gateway
        self._typing_tasks: dict[int, asyncio.Task] = {}  # Active typing indicators per chat
        self._groq_api_key = groq_api_key  # For voice transcription

    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return

        self._running = True

        # Build the application
        self._app = (
            Application.builder()
            .token(self.config.token)
            .build()
        )

        # Add message handler for text, photos, voice, documents
        self._app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL)
                & ~filters.COMMAND,
                self._on_message
            )
        )

        # Add command handlers
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("compact", self._on_compact))
        self._app.add_handler(CommandHandler("new", self._on_new))
        self._app.add_handler(CommandHandler("clear", self._on_clear))
        self._app.add_handler(CommandHandler("help", self._on_help))

        logger.info("Starting Telegram bot (polling mode)...")

        # Initialize and start polling
        await self._app.initialize()
        await self._app.start()

        # Get bot info
        bot_info = await self._app.bot.get_me()
        logger.info(f"Telegram bot @{bot_info.username} connected")

        # Register bot commands (shows in Telegram's command menu)
        try:
            await self._app.bot.set_my_commands(self.NATIVE_COMMANDS)
            logger.info(f"Registered {len(self.NATIVE_COMMANDS)} native commands")
        except Exception as e:
            logger.warning(f"Failed to set bot commands: {e}")

        # Start polling (this runs until stopped)
        await self._app.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True  # Ignore old messages on startup
        )

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False

        # Cancel all typing indicator tasks
        for chat_id in list(self._typing_tasks.keys()):
            await self._stop_typing(chat_id)

        if self._app:
            logger.info("Stopping Telegram bot...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through Telegram.

        Handles:
        - Text-only messages
        - Single photo with caption
        - Multiple photos as media group
        - Documents/files
        """
        if not self._app:
            logger.warning("Telegram bot not running")
            return

        try:
            chat_id = int(msg.chat_id)
        except ValueError:
            logger.error(f"Invalid chat_id: {msg.chat_id}")
            return

        # Stop typing indicator before sending response
        await self._stop_typing(chat_id)

        # Check if we have media to send
        if msg.media:
            await self._send_with_media(chat_id, msg)
        else:
            await self._send_text(chat_id, msg.content)

    async def _send_text(self, chat_id: int, content: str) -> None:
        """Send a text-only message."""
        if not self._app:
            return

        try:
            html_content = _markdown_to_telegram_html(content)
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=html_content,
                parse_mode="HTML"
            )
        except Exception as e:
            # Fallback to plain text if HTML parsing fails
            logger.warning(f"HTML parse failed, falling back to plain text: {e}")
            try:
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=content
                )
            except Exception as e2:
                logger.error(f"Error sending Telegram message: {e2}")

    async def _send_with_media(self, chat_id: int, msg: OutboundMessage) -> None:
        """Send message with media attachments."""
        if not self._app:
            return

        # Separate images from documents
        images: list[Path] = []
        documents: list[Path] = []

        for media_path in msg.media:
            path = Path(media_path).expanduser().resolve()

            if not path.exists():
                logger.warning(f"Media file not found: {media_path}")
                continue

            if _is_image_file(path):
                images.append(path)
            else:
                documents.append(path)

        # Send images
        if images:
            await self._send_images(chat_id, images, msg.content)
        elif msg.content:
            # No images but we have content - send as text
            await self._send_text(chat_id, msg.content)

        # Send documents separately (after images)
        for doc_path in documents:
            await self._send_document(chat_id, doc_path)

    async def _send_images(self, chat_id: int, images: list[Path], caption: str) -> None:
        """Send one or more images."""
        if not self._app or not images:
            return

        try:
            if len(images) == 1:
                # Single image - send as photo with caption
                await self._send_single_photo(chat_id, images[0], caption)
            else:
                # Multiple images - send as media group
                await self._send_media_group(chat_id, images, caption)

        except Exception as e:
            logger.error(f"Error sending images: {e}")
            # Fallback: try sending as documents
            for image in images:
                try:
                    await self._send_document(chat_id, image)
                except Exception as e2:
                    logger.error(f"Failed to send {image} as document: {e2}")

    async def _send_single_photo(self, chat_id: int, image_path: Path, caption: str) -> None:
        """Send a single photo with caption."""
        if not self._app:
            return

        # Prepare caption (truncate if needed)
        html_caption = ""
        if caption:
            html_caption = _truncate_caption(_markdown_to_telegram_html(caption))

        try:
            with open(image_path, "rb") as photo_file:
                await self._app.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(photo_file, filename=image_path.name),
                    caption=html_caption if html_caption else None,
                    parse_mode="HTML" if html_caption else None
                )
                logger.info(f"Sent photo: {image_path.name} to {chat_id}")

        except Exception as e:
            logger.error(f"Error sending photo {image_path}: {e}")
            # Try sending as document as fallback
            await self._send_document(chat_id, image_path)

    async def _send_media_group(self, chat_id: int, images: list[Path], caption: str) -> None:
        """Send multiple images as a media group."""
        if not self._app or not images:
            return

        from telegram import InputMediaPhoto

        try:
            media_group = []
            file_handles = []

            for i, image_path in enumerate(images[:10]):  # Telegram limit: 10 items
                file_handle = open(image_path, "rb")
                file_handles.append(file_handle)

                # Only first image gets the caption
                img_caption = None
                if i == 0 and caption:
                    img_caption = _truncate_caption(_markdown_to_telegram_html(caption))

                media_group.append(InputMediaPhoto(
                    media=InputFile(file_handle, filename=image_path.name),
                    caption=img_caption,
                    parse_mode="HTML" if img_caption else None
                ))

            await self._app.bot.send_media_group(
                chat_id=chat_id,
                media=media_group
            )
            logger.info(f"Sent media group with {len(images)} images to {chat_id}")

        except Exception as e:
            logger.error(f"Error sending media group: {e}")
            raise
        finally:
            # Close all file handles
            for fh in file_handles:
                try:
                    fh.close()
                except Exception:
                    pass

    async def _send_document(self, chat_id: int, doc_path: Path) -> None:
        """Send a file as a document."""
        if not self._app:
            return

        try:
            with open(doc_path, "rb") as doc_file:
                await self._app.bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(doc_file, filename=doc_path.name)
                )
                logger.info(f"Sent document: {doc_path.name} to {chat_id}")

        except Exception as e:
            logger.error(f"Error sending document {doc_path}: {e}")

    def set_compact_callback(self, callback: callable) -> None:
        """Set the callback for /compact command."""
        self._compact_callback = callback

    async def _send_typing(self, chat_id: int) -> None:
        """Send typing indicator to a chat."""
        if not self._app:
            return
        try:
            await self._app.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception as e:
            logger.debug(f"Failed to send typing indicator: {e}")

    async def _start_typing_loop(self, chat_id: int) -> None:
        """Start a background task that sends typing indicators every 4 seconds."""
        # Cancel existing typing task for this chat if any
        await self._stop_typing(chat_id)

        async def typing_loop():
            try:
                while True:
                    await self._send_typing(chat_id)
                    await asyncio.sleep(4)  # Telegram typing expires after ~5 seconds
            except asyncio.CancelledError:
                pass

        self._typing_tasks[chat_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, chat_id: int) -> None:
        """Stop the typing indicator loop for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return

        user = update.effective_user
        await update.message.reply_text(
            f"Hi {user.first_name}! I'm Flowly 🐈\n\n"
            "Send me a message and I'll respond!\n\n"
            "Commands:\n"
            "/compact - Summarize conversation\n"
            "/clear - Clear history\n"
            "/help - Show help"
        )

    async def _on_compact(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /compact command."""
        if not update.message or not update.effective_user:
            return

        chat_id = update.message.chat_id
        user = update.effective_user

        # Get optional custom instructions from command args
        custom_instructions = " ".join(context.args) if context.args else None

        if self._compact_callback:
            await update.message.reply_text("⚙️ Compacting conversation history...")
            try:
                session_key = f"telegram:{chat_id}"
                result = await self._compact_callback(session_key, custom_instructions)

                if result.get("success"):
                    await update.message.reply_text(
                        f"✅ {result['message']}\n"
                        f"({result['tokens_before']} → {result['tokens_after']} tokens)\n\n"
                        f"📝 Summary:\n{result.get('summary_preview', '')}"
                    )
                else:
                    await update.message.reply_text(f"⚠️ {result.get('message', 'Compaction failed')}")
            except Exception as e:
                logger.error(f"Compact command failed: {e}")
                await update.message.reply_text(f"❌ Error: {str(e)}")
        else:
            await update.message.reply_text("⚠️ Compaction not available")

    async def _on_new(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /new command — start a fresh session."""
        if not update.message or not update.effective_user:
            return

        chat_id = update.message.chat_id

        await self._handle_message(
            sender_id=str(update.effective_user.id),
            chat_id=str(chat_id),
            content="/new",
            metadata={"is_command": True, "command": "new"}
        )

        await update.message.reply_text("✨ New conversation started")

    async def _on_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /clear command — clear current session history."""
        if not update.message or not update.effective_user:
            return

        chat_id = update.message.chat_id

        await self._handle_message(
            sender_id=str(update.effective_user.id),
            chat_id=str(chat_id),
            content="/clear",
            metadata={"is_command": True, "command": "clear"}
        )

        await update.message.reply_text("✅ Session history cleared")

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not update.message:
            return

        await update.message.reply_text(
            "🐈 <b>Flowly Commands</b>\n\n"
            "<b>/new</b>\n"
            "Start a fresh conversation (keeps old history).\n\n"
            "<b>/compact</b> [instructions]\n"
            "Summarize conversation history to free up context space.\n"
            "Example: <code>/compact Focus on technical decisions</code>\n\n"
            "<b>/clear</b>\n"
            "Clear the current session history.\n\n"
            "<b>/help</b>\n"
            "Show this help message.\n\n"
            "💡 <i>Just send a message to chat normally!</i>",
            parse_mode="HTML"
        )

    def _is_sender_allowed(self, user_id: str, username: str | None) -> bool:
        """Check if sender is allowed via config or pairing store."""
        dm_policy = getattr(self.config, 'dm_policy', 'pairing')

        # Open mode = allow everyone
        if dm_policy == "open":
            return True

        # Check config allow_from
        config_allow = self.config.allow_from or []

        # Check pairing store allow_from
        store_allow = read_allow_from_store("telegram")

        # Combine both lists
        all_allowed = set(config_allow) | set(store_allow)

        # For pairing/allowlist mode, empty list means no one is allowed yet
        if not all_allowed:
            return False

        # Check if user_id or username matches
        if user_id in all_allowed:
            return True
        if username and username in all_allowed:
            return True
        if username and f"@{username}" in all_allowed:
            return True

        # Check with telegram: prefix
        if f"telegram:{user_id}" in all_allowed:
            return True

        return False

    async def _handle_pairing(self, chat_id: int, user) -> bool:
        """
        Handle pairing for unauthorized users.

        Returns True if user is not allowed (message blocked or pairing sent).
        """
        user_id = str(user.id)
        username = user.username

        if self._is_sender_allowed(user_id, username):
            return False

        dm_policy = getattr(self.config, 'dm_policy', 'pairing')

        # allowlist mode = silently block unauthorized users
        if dm_policy == "allowlist":
            logger.debug(f"Blocked unauthorized sender {user_id} (allowlist mode)")
            return True

        # pairing mode = send pairing code
        meta = {}
        if username:
            meta["username"] = username
        if user.first_name:
            meta["first_name"] = user.first_name
        if user.last_name:
            meta["last_name"] = user.last_name

        code, created = upsert_pairing_request("telegram", user_id, meta)

        if created and code:
            # Send pairing instructions
            await self._app.bot.send_message(
                chat_id,
                f"🔐 <b>Flowly: Access Required</b>\n\n"
                f"Your Telegram ID: <code>{user_id}</code>\n\n"
                f"Pairing code: <code>{code}</code>\n\n"
                f"Ask the bot owner to approve:\n"
                f"<code>flowly pairing approve telegram {code}</code>",
                parse_mode="HTML"
            )
            logger.info(f"Pairing request created for {user_id} ({username}): {code}")
        elif not code:
            # Max pending reached
            await self._app.bot.send_message(
                chat_id,
                "⚠️ Too many pending requests. Please try again later."
            )

        return True

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id

        # Check pairing / authorization first
        if await self._handle_pairing(chat_id, user):
            return  # User not authorized, pairing message sent

        # Start typing indicator loop (will continue until response is sent)
        await self._start_typing_loop(chat_id)

        # Use stable numeric ID, but keep username for allowlist compatibility
        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        # Store chat_id for replies
        self._chat_ids[sender_id] = chat_id

        # Build content from text and/or media
        content_parts = []
        media_paths = []

        # Text content
        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        # Handle media files
        media_file = None
        media_type = None

        if message.photo:
            media_file = message.photo[-1]  # Largest photo
            media_type = "image"
        elif message.voice:
            media_file = message.voice
            media_type = "voice"
        elif message.audio:
            media_file = message.audio
            media_type = "audio"
        elif message.document:
            media_file = message.document
            media_type = "file"

        # Download media if present
        if media_file and self._app:
            try:
                file = await self._app.bot.get_file(media_file.file_id)
                ext = self._get_extension(media_type, getattr(media_file, 'mime_type', None))

                # Save to workspace/media/
                media_dir = Path.home() / ".flowly" / "media"
                media_dir.mkdir(parents=True, exist_ok=True)

                file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
                await file.download_to_drive(str(file_path))

                media_paths.append(str(file_path))

                # Transcribe voice/audio messages using Groq Whisper
                if media_type in ("voice", "audio") and self._groq_api_key:
                    try:
                        from flowly.providers.transcription import GroqTranscriptionProvider
                        transcriber = GroqTranscriptionProvider(self._groq_api_key)
                        transcript = await transcriber.transcribe(file_path)
                        if transcript:
                            content_parts.append(f"[transcription: {transcript}]")
                            logger.info(f"Transcribed {media_type}: {transcript[:50]}...")
                        else:
                            content_parts.append(f"[{media_type}: {file_path}]")
                    except Exception as e:
                        logger.error(f"Transcription failed: {e}")
                        content_parts.append(f"[{media_type}: {file_path}]")
                else:
                    content_parts.append(f"[{media_type}: {file_path}]")

                logger.debug(f"Downloaded {media_type} to {file_path}")
            except Exception as e:
                logger.error(f"Failed to download media: {e}")
                content_parts.append(f"[{media_type}: download failed]")

        content = "\n".join(content_parts) if content_parts else "[empty message]"

        logger.debug(f"Telegram message from {sender_id}: {content[:50]}...")

        # Forward to the message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str(chat_id),
            content=content,
            media=media_paths,
            metadata={
                "message_id": message.message_id,
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "is_group": message.chat.type != "private"
            }
        )

    def _get_extension(self, media_type: str, mime_type: str | None) -> str:
        """Get file extension based on media type."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]

        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "file": ""}
        return type_map.get(media_type, "")
