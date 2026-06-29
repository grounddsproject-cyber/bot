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
import os
import platform
import subprocess
import signal
from dotenv import load_dotenv
load_dotenv()

# ========== КОНФИГ ==========
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "1505883412928659536"))

if not TOKEN:
    print("DISCORD_TOKEN не задан! Добавь его в .env или переменные окружения хоста.")
    sys.exit(1)

# ========== ЛОГИРОВАНИЕ ==========
log_formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Ротация логов: максимум 5 МБ, хранит 3 последних файла
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
scheduler = AsyncIOScheduler(timezone=moscow_tz)

# ========== БОТ ==========
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ========== ЗАЩИТА ОТ СНА ==========
AWAKE_MODE = True
_caffeinate_proc = None   # subprocess для caffeinate/systemd-inhibit


def _platform_inhibit_start():
    """
    Запускает системный блокировщик сна в зависимости от ОС.
    Возвращает subprocess.Popen или None.
    """
    system = platform.system()
    try:
        if system == "Darwin":
            # macOS: caffeinate держит систему бодрой, пока процесс жив
            proc = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
            logger.info("☕ caffeinate запущен (macOS)")
            return proc

        elif system == "Linux":
            # Linux: пробуем systemd-inhibit
            proc = subprocess.Popen(
                ["systemd-inhibit", "--what=idle:sleep", "--who=NoSleepBot",
                 "--why=Discord bot running", "--mode=block",
                 "sleep", "infinity"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info("🛡️ systemd-inhibit запущен (Linux)")
            return proc

        elif system == "Windows":
            # Windows: SetThreadExecutionState через ctypes
            try:
                import ctypes
                # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
                logger.info("🖱️ SetThreadExecutionState активирован (Windows)")
            except Exception as e:
                logger.warning(f"SetThreadExecutionState не сработал: {e}")
            return None

    except FileNotFoundError:
        logger.warning(f"Системный блокировщик сна недоступен на {system}")
        return None
    except Exception as e:
        logger.error(f"Ошибка запуска блокировщика сна: {e}")
        return None


def _platform_inhibit_stop(proc):
    """Останавливает системный блокировщик сна."""
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        logger.info("🛑 Блокировщик сна остановлен")

    # Windows: снимаем флаг
    if platform.system() == "Windows":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS
        except Exception:
            pass


async def keep_awake():
    """
    Основной цикл защиты от сна.
    Каждые 30 секунд делает «heartbeat» в лог — виден на хосте.
    Каждые 4 минуты пересоздаёт caffeinate-процесс если он упал.
    """
    global _caffeinate_proc, AWAKE_MODE

    _caffeinate_proc = _platform_inhibit_start()
    tick = 0

    while True:
        await asyncio.sleep(30)
        tick += 1

        if not AWAKE_MODE:
            continue

        # Heartbeat каждые 5 тиков (2.5 мин)
        if tick % 5 == 0:
            logger.info("💓 keep_awake heartbeat — бот активен")

        # Переподнимаем caffeinate если он упал (раз в ~4 мин)
        if tick % 8 == 0:
            if _caffeinate_proc and _caffeinate_proc.poll() is not None:
                logger.warning("⚠️ Блокировщик сна упал — перезапускаю")
                _caffeinate_proc = _platform_inhibit_start()

        # Windows: обновляем SetThreadExecutionState каждую минуту
        if platform.system() == "Windows" and tick % 2 == 0:
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
            except Exception:
                pass


# ========== НАПОМИНАНИЯ ==========

async def send_kv_reminder_30():
    """Напоминание за 30 минут"""
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            await channel.send("@everyone Через 30 минут кв")
            logger.info("📢 Напоминание за 30 мин отправлено")
        else:
            logger.error(f"Канал с ID {CHANNEL_ID} не найден!")
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминания за 30 мин: {e}", exc_info=True)


async def send_kv_reminder_15():
    """Напоминание за 15 минут"""
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            await channel.send("@everyone Через 15 минут кв")
            logger.info("📢 Напоминание за 15 мин отправлено")
        else:
            logger.error(f"Канал с ID {CHANNEL_ID} не найден!")
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминания за 15 мин: {e}", exc_info=True)


# ========== КОНСОЛЬНЫЕ КОМАНДЫ ==========

def console_commands():
    """Обработчик команд из консоли"""
    global AWAKE_MODE, _caffeinate_proc

    _print_help()

    while True:
        try:
            cmd = input(">>> ").strip()

            if not cmd:
                continue

            # --- Команды в чат ---
            if cmd.startswith("!chat "):
                chat_cmd = cmd[6:].strip()
                channel = bot.get_channel(CHANNEL_ID)

                if channel is None:
                    print("❌ Канал не найден! Проверь CHANNEL_ID")
                    continue

                if chat_cmd == "test30":
                    asyncio.run_coroutine_threadsafe(send_kv_reminder_30(), bot.loop)
                    print("✅ Отправлено в чат: @everyone Через 30 минут кв")

                elif chat_cmd == "test15":
                    asyncio.run_coroutine_threadsafe(send_kv_reminder_15(), bot.loop)
                    print("✅ Отправлено в чат: @everyone Через 15 минут кв")

                elif chat_cmd == "status":
                    asyncio.run_coroutine_threadsafe(_send_status_to_chat(), bot.loop)
                    print("✅ Статус отправлен в чат")

                else:
                    print(f"❌ Неизвестная команда для чата: {chat_cmd}")
                    print("   Доступные: test30, test15, status")

            # --- Локальные команды ---
            elif cmd == "test30":
                print("📢 [КОНСОЛЬ] @everyone Через 30 минут кв")
                print("   (Для отправки в чат: !chat test30)")

            elif cmd == "test15":
                print("📢 [КОНСОЛЬ] @everyone Через 15 минут кв")
                print("   (Для отправки в чат: !chat test15)")

            elif cmd == "status":
                _print_status()

            elif cmd == "time":
                now = datetime.now(moscow_tz)
                print(f"\n🕐 Московское время: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")

            elif cmd == "awake on":
                AWAKE_MODE = True
                if _caffeinate_proc is None or _caffeinate_proc.poll() is not None:
                    _caffeinate_proc = _platform_inhibit_start()
                asyncio.run_coroutine_threadsafe(_update_presence(), bot.loop)
                print("✅ Защита от сна ВКЛЮЧЕНА")
                logger.info("Защита от сна включена")

            elif cmd == "awake off":
                AWAKE_MODE = False
                _platform_inhibit_stop(_caffeinate_proc)
                _caffeinate_proc = None
                asyncio.run_coroutine_threadsafe(_update_presence(), bot.loop)
                print("❌ Защита от сна ВЫКЛЮЧЕНА")
                logger.info("Защита от сна выключена")

            elif cmd == "help":
                _print_help()

            elif cmd == "exit":
                print("⏹️ Выключаю бота...")
                asyncio.run_coroutine_threadsafe(_graceful_shutdown(), bot.loop)
                break

            else:
                print(f"❌ Неизвестная команда: '{cmd}'")
                print("   Введите 'help' для списка команд")

        except EOFError:
            # Хост без интерактивного терминала — молча выходим
            logger.info("stdin закрыт (нет терминала) — консоль отключена")
            break
        except Exception as e:
            print(f"❌ Ошибка: {e}")


def _print_help():
    print("\n" + "=" * 52)
    print("  КОНСОЛЬ УПРАВЛЕНИЯ БОТОМ")
    print("=" * 52)
    print("  Локальные команды:")
    print("    test30     — тест напоминания 30 мин")
    print("    test15     — тест напоминания 15 мин")
    print("    status     — статус бота")
    print("    time       — московское время")
    print("    awake on   — включить защиту от сна")
    print("    awake off  — выключить защиту от сна")
    print("    help       — это сообщение")
    print("    exit       — остановить бота")
    print()
    print("  Команды в Discord-чат:")
    print("    !chat test30")
    print("    !chat test15")
    print("    !chat status")
    print("=" * 52 + "\n")


def _print_status():
    now = datetime.now(moscow_tz)
    jobs = scheduler.get_jobs()
    sys_name = platform.system()
    inhibit_ok = (_caffeinate_proc is not None and _caffeinate_proc.poll() is None)

    print(f"\n📊 СТАТУС БОТА:")
    print(f"   🕐 Время (МСК):      {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   🖥️  ОС:              {sys_name}")
    print(f"   🛡️  Защита от сна:   {'✅ Вкл' if AWAKE_MODE else '❌ Выкл'}")
    if AWAKE_MODE:
        if sys_name == "Windows":
            print(f"   🔧 Метод:           SetThreadExecutionState (Windows)")
        elif inhibit_ok:
            print(f"   🔧 Метод:           {'caffeinate' if sys_name == 'Darwin' else 'systemd-inhibit'} ✅")
        else:
            print(f"   🔧 Метод:           heartbeat (fallback)")
    print(f"   📋 Задач планировщика: {len(jobs)}")
    for job in jobs:
        next_run = (
            job.next_run_time.astimezone(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')
            if job.next_run_time else "нет"
        )
        print(f"      • {job.id}: следующий запуск {next_run}")
    print()


async def _send_status_to_chat():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
    now = datetime.now(moscow_tz)
    jobs = scheduler.get_jobs()
    inhibit_ok = (_caffeinate_proc is not None and _caffeinate_proc.poll() is None)

    msg = f"🕐 Московское время: `{now.strftime('%Y-%m-%d %H:%M:%S')}`\n"
    msg += f"🛡️ Защита от сна: {'✅ Вкл' if AWAKE_MODE else '❌ Выкл'}"
    if AWAKE_MODE:
        method = "SetThreadExecutionState" if platform.system() == "Windows" \
            else ("caffeinate" if platform.system() == "Darwin" else "systemd-inhibit")
        msg += f" ({method})\n" if inhibit_ok or platform.system() == "Windows" else " (heartbeat fallback)\n"
    else:
        msg += "\n"
    msg += f"📋 Активных задач: {len(jobs)}\n"
    for job in jobs:
        next_run = (
            job.next_run_time.astimezone(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')
            if job.next_run_time else "нет"
        )
        msg += f"• `{job.id}`: следующий запуск `{next_run}`\n"

    await channel.send(msg)


async def _update_presence():
    """Обновляет статус бота в Discord в зависимости от AWAKE_MODE."""
    if AWAKE_MODE:
        activity = discord.Activity(type=discord.ActivityType.watching, name="🛡️ Защита от сна ВКЛ")
        status = discord.Status.online
    else:
        activity = discord.Activity(type=discord.ActivityType.watching, name="😴 Защита от сна ВЫКЛ")
        status = discord.Status.idle
    await bot.change_presence(status=status, activity=activity)


async def _graceful_shutdown():
    """Корректное завершение бота."""
    logger.info("Начинаю graceful shutdown...")
    _platform_inhibit_stop(_caffeinate_proc)
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await bot.close()


# ========== СОБЫТИЯ БОТА ==========

@bot.event
async def on_ready():
    logger.info(f"Бот {bot.user} запущен!")
    logger.info(f"Московское время: {datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"ОС: {platform.system()} {platform.release()}")

    # Запускаем защиту от сна
    bot.loop.create_task(keep_awake())

    # Планируем задачи
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

    # Консоль в отдельном потоке (daemon=True — не мешает shutdown)
    console_thread = threading.Thread(target=console_commands, daemon=True, name="ConsoleThread")
    console_thread.start()

    await _update_presence()
    logger.info("Бот полностью готов к работе ✅")


@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Ошибка в событии {event}:", exc_info=True)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error(f"Ошибка в команде {ctx.command}: {error}", exc_info=True)


# ========== КОМАНДЫ DISCORD ==========

@bot.command(name="status")
async def status_command(ctx):
    now = datetime.now(moscow_tz)
    jobs = scheduler.get_jobs()
    inhibit_ok = (_caffeinate_proc is not None and _caffeinate_proc.poll() is None)

    msg = f"🕐 Московское время: `{now.strftime('%Y-%m-%d %H:%M:%S')}`\n"
    msg += f"🛡️ Защита от сна: {'✅ Вкл' if AWAKE_MODE else '❌ Выкл'}"
    if AWAKE_MODE:
        method = "SetThreadExecutionState" if platform.system() == "Windows" \
            else ("caffeinate" if platform.system() == "Darwin" else "systemd-inhibit")
        msg += f" ({method})\n" if inhibit_ok or platform.system() == "Windows" else " (heartbeat fallback)\n"
    else:
        msg += "\n"
    msg += f"📋 Активных задач: {len(jobs)}\n"
    for job in jobs:
        next_run = (
            job.next_run_time.astimezone(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')
            if job.next_run_time else "нет"
        )
        msg += f"• `{job.id}`: следующий запуск `{next_run}`\n"

    await ctx.send(msg)


# ========== СИГНАЛЫ ОС (для Linux/Mac хостов) ==========
def _setup_signal_handlers():
    """Подключает SIGTERM/SIGINT для корректного завершения на хосте."""
    def _handle_signal(sig, frame):
        logger.info(f"Получен сигнал {sig} — завершаю работу...")
        if bot.loop and bot.loop.is_running():
            asyncio.run_coroutine_threadsafe(_graceful_shutdown(), bot.loop)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)


# ========== ТОЧКА ВХОДА ==========
if __name__ == "__main__":
    _setup_signal_handlers()

    logger.info("=" * 50)
    logger.info("ЗАПУСК БОТА")
    logger.info(f"Время запуска: {datetime.now(moscow_tz).strftime('%Y-%m-%d %H:%M:%S')} МСК")
    logger.info(f"Python {sys.version}")
    logger.info(f"ОС: {platform.system()} {platform.release()}")
    logger.info("=" * 50)

    try:
        bot.run(TOKEN, log_handler=None)  # log_handler=None — используем наш логгер
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем (KeyboardInterrupt)")
    except discord.LoginFailure:
        logger.critical("❌ Неверный токен! Проверь DISCORD_TOKEN")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
