import discord
from discord.ext import commands
from discord.ui import View, Button
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from datetime import datetime
import logging
import logging.handlers
import sys
import asyncio
import threading
import signal
import os
from dotenv import load_dotenv
load_dotenv()

# ========== КОНФИГ ==========
TOKEN      = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))  # Канал для напоминаний КВ
PANEL_CHANNEL_ID = 1521239496908083272                   # Канал для панели (строго один раз)

# Файл для хранения ID сообщения панели
PANEL_MSG_FILE = "panel_message_id.txt"

# Цвета embed'ов
COLOR_REMINDER = 0xE74C3C   # красный — напоминание
COLOR_STATUS   = 0x5865F2   # синий   — статус
COLOR_PANEL    = 0xEB459E   # розовый — панель управления

# ========== ЛОГИРОВАНИЕ ==========
log_formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler = logging.handlers.RotatingFileHandler(
    'bot_log.txt', maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8'
)
file_handler.setFormatter(log_formatter)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# ========== TIMEZONE / SCHEDULER ==========
moscow_tz = pytz.timezone('Europe/Moscow')
scheduler  = AsyncIOScheduler(timezone=moscow_tz)

# ========== БОТ ==========
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


# ========== ПАНЕЛЬ: СОХРАНЕНИЕ ID ==========

def _save_panel_msg_id(msg_id: int):
    with open(PANEL_MSG_FILE, "w") as f:
        f.write(str(msg_id))

def _load_panel_msg_id() -> int | None:
    if not os.path.exists(PANEL_MSG_FILE):
        return None
    try:
        with open(PANEL_MSG_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return None

def _clear_panel_msg_id():
    if os.path.exists(PANEL_MSG_FILE):
        os.remove(PANEL_MSG_FILE)


# ========== EMBEDS ==========

def make_reminder_embed(minutes: int) -> discord.Embed:
    now = datetime.now(moscow_tz)
    embed = discord.Embed(
        title="⚔️  Напоминание о КВ",
        description=f"# Через **{minutes} минут** начинается **КВ**!\nПодготовьтесь и займите места.",
        color=COLOR_REMINDER,
        timestamp=now
    )
    embed.add_field(name="🕐 Время начала", value="`20:00 МСК`", inline=True)
    embed.add_field(name="⏳ Осталось", value=f"`{minutes} мин`", inline=True)
    embed.set_footer(text="Клановая война • Напоминание")
    return embed


def make_status_embed() -> discord.Embed:
    now  = datetime.now(moscow_tz)
    jobs = scheduler.get_jobs()
    embed = discord.Embed(
        title="📊  Статус бота",
        color=COLOR_STATUS,
        timestamp=now
    )
    embed.add_field(
        name="🕐 Время (МСК)",
        value=f"`{now.strftime('%Y-%m-%d %H:%M:%S')}`",
        inline=False
    )
    if jobs:
        tasks_text = ""
        for job in jobs:
            next_run = (
                job.next_run_time.astimezone(moscow_tz).strftime('%d.%m.%Y %H:%M:%S')
                if job.next_run_time else "—"
            )
            tasks_text += f"• **{job.id}** → `{next_run}`\n"
        embed.add_field(name=f"📋 Активных задач: {len(jobs)}", value=tasks_text, inline=False)
    else:
        embed.add_field(name="📋 Задачи", value="Нет активных задач", inline=False)
    embed.set_footer(text="KV Bot • Статус")
    return embed


def make_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎮  Панель управления KV Bot",
        description="Используй кнопки ниже для управления ботом.",
        color=COLOR_PANEL
    )
    embed.add_field(
        name="📊 Статус",
        value="Показать статус бота — только себе или всем в чате",
        inline=False
    )
    embed.add_field(
        name="⚔️ Тест напоминаний",
        value="Отправить тестовое напоминание — только себе или в КВ-канал",
        inline=False
    )
    embed.set_footer(text="KV Bot • Панель управления")
    return embed


# ========== VIEWS (КНОПКИ) ==========

class ReminderTargetView(View):
    def __init__(self, minutes: int):
        super().__init__(timeout=30)
        self.minutes = minutes

    @discord.ui.button(label="👤 Только мне", style=discord.ButtonStyle.secondary)
    async def send_private(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(embed=make_reminder_embed(self.minutes), ephemeral=True)
        self._disable_all()
        await interaction.message.edit(view=self)
        logger.info(f"Тест {self.minutes} мин — личное для {interaction.user}")

    @discord.ui.button(label="📢 В КВ-канал", style=discord.ButtonStyle.danger)
    async def send_to_channel(self, interaction: discord.Interaction, button: Button):
        kv_channel = bot.get_channel(CHANNEL_ID)
        if kv_channel:
            await kv_channel.send("@everyone", embed=make_reminder_embed(self.minutes))
            await interaction.response.send_message(
                f"✅ Напоминание за {self.minutes} мин отправлено в <#{CHANNEL_ID}>",
                ephemeral=True
            )
            logger.info(f"Тест {self.minutes} мин — в КВ-канал ({interaction.user})")
        else:
            await interaction.response.send_message("❌ КВ-канал не найден!", ephemeral=True)
        self._disable_all()
        await interaction.message.edit(view=self)

    @discord.ui.button(label="✖ Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        self._disable_all()
        await interaction.message.edit(view=self)

    def _disable_all(self):
        for item in self.children:
            item.disabled = True

    async def on_timeout(self):
        self._disable_all()


class StatusTargetView(View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="👤 Только мне", style=discord.ButtonStyle.secondary)
    async def send_private(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(embed=make_status_embed(), ephemeral=True)
        self._disable_all()
        await interaction.message.edit(view=self)
        logger.info(f"Статус (личный) — {interaction.user}")

    @discord.ui.button(label="📢 Всем в чате", style=discord.ButtonStyle.primary)
    async def send_public(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(embed=make_status_embed())
        self._disable_all()
        await interaction.message.edit(view=self)
        logger.info(f"Статус (публичный) — {interaction.user}")

    @discord.ui.button(label="✖ Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        self._disable_all()
        await interaction.message.edit(view=self)

    def _disable_all(self):
        for item in self.children:
            item.disabled = True

    async def on_timeout(self):
        self._disable_all()


class PanelView(View):
    """Главная панель — живёт вечно, отправляется строго один раз."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📊 Статус", style=discord.ButtonStyle.primary, custom_id="panel:status", row=0)
    async def status_btn(self, interaction: discord.Interaction, button: Button):
        view = StatusTargetView()
        await interaction.response.send_message("Куда показать статус?", view=view, ephemeral=True)

    @discord.ui.button(label="⚔️ Тест 30 мин", style=discord.ButtonStyle.danger, custom_id="panel:test30", row=1)
    async def test30_btn(self, interaction: discord.Interaction, button: Button):
        view = ReminderTargetView(30)
        await interaction.response.send_message(
            "Куда отправить напоминание за **30 минут**?", view=view, ephemeral=True
        )

    @discord.ui.button(label="⚔️ Тест 15 мин", style=discord.ButtonStyle.danger, custom_id="panel:test15", row=1)
    async def test15_btn(self, interaction: discord.Interaction, button: Button):
        view = ReminderTargetView(15)
        await interaction.response.send_message(
            "Куда отправить напоминание за **15 минут**?", view=view, ephemeral=True
        )


# ========== ОТПРАВКА ПАНЕЛИ (один раз) ==========

async def setup_panel():
    """
    Отправляет панель строго один раз в PANEL_CHANNEL_ID.
    При перезапуске бота находит старое сообщение и восстанавливает view,
    не отправляя новое.
    """
    channel = bot.get_channel(PANEL_CHANNEL_ID)
    if not channel:
        logger.error(f"Канал панели {PANEL_CHANNEL_ID} не найден!")
        return

    saved_id = _load_panel_msg_id()

    # Пробуем найти существующее сообщение панели
    if saved_id:
        try:
            msg = await channel.fetch_message(saved_id)
            # Сообщение существует — просто восстанавливаем view (после перезапуска)
            await msg.edit(embed=make_panel_embed(), view=PanelView())
            logger.info(f"Панель восстановлена (msg_id={saved_id})")
            return
        except discord.NotFound:
            logger.warning("Сохранённое сообщение панели удалено — отправлю новое")
            _clear_panel_msg_id()
        except Exception as e:
            logger.error(f"Ошибка восстановления панели: {e}")

    # Отправляем панель впервые
    msg = await channel.send(embed=make_panel_embed(), view=PanelView())
    _save_panel_msg_id(msg.id)
    logger.info(f"Панель отправлена впервые (msg_id={msg.id})")


# ========== НАПОМИНАНИЯ (планировщик) ==========

async def send_kv_reminder_30():
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            await channel.send("@everyone", embed=make_reminder_embed(30))
            logger.info("Напоминание за 30 мин отправлено")
        else:
            logger.error(f"Канал {CHANNEL_ID} не найден!")
    except Exception as e:
        logger.error(f"Ошибка напоминания 30 мин: {e}", exc_info=True)


async def send_kv_reminder_15():
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            await channel.send("@everyone", embed=make_reminder_embed(15))
            logger.info("Напоминание за 15 мин отправлено")
        else:
            logger.error(f"Канал {CHANNEL_ID} не найден!")
    except Exception as e:
        logger.error(f"Ошибка напоминания 15 мин: {e}", exc_info=True)


# ========== КОНСОЛЬНЫЕ КОМАНДЫ ==========

def console_commands():
    _print_help()
    while True:
        try:
            cmd = input(">>> ").strip()
            if not cmd:
                continue

            if cmd.startswith("!chat "):
                chat_cmd = cmd[6:].strip()
                channel  = bot.get_channel(CHANNEL_ID)
                if channel is None:
                    print("Канал не найден!")
                    continue
                if chat_cmd == "test30":
                    asyncio.run_coroutine_threadsafe(send_kv_reminder_30(), bot.loop)
                    print("Отправлено: напоминание 30 мин")
                elif chat_cmd == "test15":
                    asyncio.run_coroutine_threadsafe(send_kv_reminder_15(), bot.loop)
                    print("Отправлено: напоминание 15 мин")
                else:
                    print(f"Неизвестная команда: {chat_cmd} | Доступные: test30, test15")

            elif cmd == "test30":
                print("[КОНСОЛЬ] Тест 30 мин | Для отправки в чат: !chat test30")
            elif cmd == "test15":
                print("[КОНСОЛЬ] Тест 15 мин | Для отправки в чат: !chat test15")
            elif cmd == "status":
                _print_status()
            elif cmd == "time":
                print(f"Московское время: {datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')}")
            elif cmd == "help":
                _print_help()
            elif cmd == "exit":
                print("Выключаю бота...")
                asyncio.run_coroutine_threadsafe(_graceful_shutdown(), bot.loop)
                break
            else:
                print(f"Неизвестная команда: '{cmd}'. Введите 'help'.")

        except EOFError:
            logger.info("stdin закрыт — консоль отключена")
            break
        except Exception as e:
            print(f"Ошибка: {e}")


def _print_help():
    print("\n" + "=" * 50)
    print("  КОНСОЛЬ УПРАВЛЕНИЯ БОТОМ")
    print("=" * 50)
    print("  test30        — тест напоминания 30 мин")
    print("  test15        — тест напоминания 15 мин")
    print("  status        — статус бота")
    print("  time          — московское время")
    print("  help          — эта справка")
    print("  exit          — остановить бота")
    print()
    print("  !chat test30  — напоминание в КВ-канал")
    print("  !chat test15  — напоминание в КВ-канал")
    print("=" * 50 + "\n")


def _print_status():
    now  = datetime.now(moscow_tz)
    jobs = scheduler.get_jobs()
    print(f"\n  СТАТУС БОТА")
    print(f"  Время (МСК):    {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Активных задач: {len(jobs)}")
    for job in jobs:
        next_run = (
            job.next_run_time.astimezone(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')
            if job.next_run_time else "нет"
        )
        print(f"    • {job.id}: {next_run}")
    print()


# ========== СЛУЖЕБНЫЕ ==========

async def _graceful_shutdown():
    logger.info("Graceful shutdown...")
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await bot.close()


def _setup_signal_handlers():
    def _handle(sig, frame):
        logger.info(f"Сигнал {sig} — завершаю работу...")
        if bot.loop and bot.loop.is_running():
            asyncio.run_coroutine_threadsafe(_graceful_shutdown(), bot.loop)
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT,  _handle)


# ========== СОБЫТИЯ ==========

@bot.event
async def on_ready():
    logger.info(f"Бот {bot.user} запущен!")
    logger.info(f"Время: {datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')} МСК")

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(type=discord.ActivityType.watching, name="КВ 20:00 МСК")
    )

    scheduler.add_job(
        send_kv_reminder_30,
        CronTrigger(hour=19, minute=30, timezone=moscow_tz),
        id='kv_reminder_30',
        replace_existing=True
    )
    scheduler.add_job(
        send_kv_reminder_15,
        CronTrigger(hour=19, minute=45, timezone=moscow_tz),
        id='kv_reminder_15',
        replace_existing=True
    )
    scheduler.start()
    logger.info("Планировщик запущен!")

    # Панель — строго один раз в нужный канал
    await setup_panel()

    threading.Thread(target=console_commands, daemon=True, name="ConsoleThread").start()
    logger.info("Бот готов к работе!")


@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Ошибка в событии {event}:", exc_info=True)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error(f"Ошибка в команде {ctx.command}: {error}", exc_info=True)


# ========== ТОЧКА ВХОДА ==========
if __name__ == "__main__":
    _setup_signal_handlers()

    logger.info("=" * 50)
    logger.info("ЗАПУСК БОТА")
    logger.info(f"Время: {datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')} МСК")
    logger.info("=" * 50)

    try:
        bot.run(TOKEN, log_handler=None)
    except KeyboardInterrupt:
        logger.info("Остановлен пользователем")
    except discord.LoginFailure:
        logger.critical("Неверный токен!")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
