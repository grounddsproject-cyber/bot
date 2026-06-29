import discord
from discord.ext import commands
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
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
 
if not TOKEN:
    print("DISCORD_TOKEN не задан! Добавь его в .env или переменные окружения хоста.")
    sys.exit(1)
if not CHANNEL_ID:
    print("DISCORD_CHANNEL_ID не задан! Добавь его в .env или переменные окружения хоста.")
    sys.exit(1)
 
# Цвета embed'ов
COLOR_REMINDER = 0xE74C3C   # красный — напоминание
COLOR_STATUS   = 0x5865F2   # синий   — статус
COLOR_OK       = 0x2ECC71   # зелёный — успех
 
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
 
 
# ========== EMBEDS ==========
 
def make_reminder_embed(minutes: int) -> discord.Embed:
    """Красивый embed для напоминания о кв."""
    now = datetime.now(moscow_tz)
 
    embed = discord.Embed(
        title="⚔️  Напоминание о КВ",
        description=f"# Через **{minutes} минут** начинается **КВ**!\nПодготовьтесь и займите места.",
        color=COLOR_REMINDER,
        timestamp=now
    )
    embed.add_field(
        name="🕐 Время начала",
        value="`20:00 МСК`",
        inline=True
    )
    embed.add_field(
        name="⏳ Осталось",
        value=f"`{minutes} мин`",
        inline=True
    )
    embed.set_footer(text="Клановая война • Напоминание")
    return embed
 
 
def make_status_embed(jobs) -> discord.Embed:
    """Красивый embed для !status."""
    now = datetime.now(moscow_tz)
 
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
        embed.add_field(
            name=f"📋 Активных задач: {len(jobs)}",
            value=tasks_text,
            inline=False
        )
    else:
        embed.add_field(name="📋 Задачи", value="Нет активных задач", inline=False)
 
    embed.set_footer(text="KV Bot • Статус")
    return embed
 
 
# ========== НАПОМИНАНИЯ ==========
 
async def send_kv_reminder_30():
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            embed = make_reminder_embed(30)
            await channel.send("@everyone", embed=embed)
            logger.info("Напоминание за 30 мин отправлено")
        else:
            logger.error(f"Канал {CHANNEL_ID} не найден!")
    except Exception as e:
        logger.error(f"Ошибка напоминания 30 мин: {e}", exc_info=True)
 
 
async def send_kv_reminder_15():
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            embed = make_reminder_embed(15)
            await channel.send("@everyone", embed=embed)
            logger.info("Напоминание за 15 мин отправлено")
        else:
            logger.error(f"Канал {CHANNEL_ID} не найден!")
    except Exception as e:
        logger.error(f"Ошибка напоминания 15 мин: {e}", exc_info=True)
 
 
# ========== КОМАНДЫ DISCORD ==========
 
@bot.command(name="status")
async def status_command(ctx):
    """!status — показывает статус бота в embed'е."""
    jobs = scheduler.get_jobs()
    embed = make_status_embed(jobs)
    await ctx.send(embed=embed)
    logger.info(f"!status запрошен пользователем {ctx.author}")
 
 
# ========== КОНСОЛЬНЫЕ КОМАНДЫ ==========
 
def console_commands():
    _print_help()
    while True:
        try:
            cmd = input(">>> ").strip()
            if not cmd:
                continue
 
            # Команды в чат
            if cmd.startswith("!chat "):
                chat_cmd = cmd[6:].strip()
                channel  = bot.get_channel(CHANNEL_ID)
                if channel is None:
                    print("Канал не найден! Проверь DISCORD_CHANNEL_ID в .env")
                    continue
 
                if chat_cmd == "test30":
                    asyncio.run_coroutine_threadsafe(send_kv_reminder_30(), bot.loop)
                    print("Отправлено: напоминание 30 мин")
                elif chat_cmd == "test15":
                    asyncio.run_coroutine_threadsafe(send_kv_reminder_15(), bot.loop)
                    print("Отправлено: напоминание 15 мин")
                else:
                    print(f"Неизвестная команда для чата: {chat_cmd}")
                    print("   Доступные: test30, test15")
 
            # Локальные команды
            elif cmd == "test30":
                print("[КОНСОЛЬ] Тест напоминания 30 мин")
                print("   Для отправки в чат: !chat test30")
 
            elif cmd == "test15":
                print("[КОНСОЛЬ] Тест напоминания 15 мин")
                print("   Для отправки в чат: !chat test15")
 
            elif cmd == "status":
                _print_status()
 
            elif cmd == "time":
                now = datetime.now(moscow_tz)
                print(f"Московское время: {now.strftime('%Y-%m-%d %H:%M:%S')}")
 
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
    print("  test30        — тест напоминания 30 мин (консоль)")
    print("  test15        — тест напоминания 15 мин (консоль)")
    print("  status        — статус бота")
    print("  time          — московское время")
    print("  help          — эта справка")
    print("  exit          — остановить бота")
    print()
    print("  !chat test30  — отправить напоминание в Discord")
    print("  !chat test15  — отправить напоминание в Discord")
    print()
    print("  Discord команды:")
    print("  !status       — статус бота в чате")
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
        logger.critical("Неверный токен! Проверь DISCORD_TOKEN в .env")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
