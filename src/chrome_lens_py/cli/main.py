import argparse
import asyncio
import logging
import os
import sys
import json

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.text import Text

from ..api import LensAPI
from ..exceptions import LensException
from ..utils.config_manager import build_app_config, get_config_file_path, update_config_file_from_cli
from ..utils.general import is_image_file_supported
from ..constants import APP_NAME_FOR_CONFIG, DEFAULT_CONFIG_FILENAME, DEFAULT_CLIENT_REGION, DEFAULT_CLIENT_TIME_ZONE, DEFAULT_OCR_LANG

console = Console()

def setup_logging(level_str: str = "WARNING"):
    log_level = getattr(logging, level_str.upper(), logging.WARNING)
    
    if log_level <= logging.DEBUG:
        log_format = "[%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
        show_path = True
    else:
        log_format = "%(message)s"
        show_path = False

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[RichHandler(
            console=console,
            show_time=False,
            show_level=log_level <= logging.INFO,
            show_path=show_path,
            markup=True,
            rich_tracebacks=True,
            tracebacks_show_locals=log_level <= logging.DEBUG,
        )]
    )
    if log_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.debug(f"Logging level set to {level_str.upper()}")


def print_help():
    console.print("\n[bold cyan]Google Lens CLI (chrome-lens-py vNEXT)[/bold cyan]")
    console.print("Распознает текст на изображении и опционально переводит его.")
    
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="green")
    table.add_column()

    table.add_row("Использование:", "lens_scan <путь_к_изображению> [язык_ocr] [опции]") # язык_ocr стал опциональным
    table.add_row("")
    table.add_row("[bold]Позиционные аргументы:[/bold]")
    table.add_row("  image_path", "Путь к файлу изображения.")
    default_ocr_lang_display = DEFAULT_OCR_LANG if DEFAULT_OCR_LANG else 'auto'
    table.add_row("  ocr_lang", f"BCP 47 код языка для OCR (например, 'en', 'ja'). Если не указан, сервер попытается определить язык автоматически (по умолчанию: '{default_ocr_lang_display}').")
    table.add_row("")
    table.add_row("[bold]Опции перевода:[/bold]")
    table.add_row("  -t, --translate TARGET_LANG", "BCP 47 код целевого языка для перевода (например, 'en', 'ru').")
    table.add_row("  --translate-from SOURCE_LANG", "BCP 47 код исходного языка для перевода (если не указан, определяется автоматически).")
    table.add_row("  -to, --translate-out FILE_PATH", "Сохранить изображение с наложенным переводом в указанный файл.")
    table.add_row("")
    table.add_row("[bold]Опции конфигурации и вывода:[/bold]")
    table.add_row("  --config-file FILE_PATH", f"Путь к файлу конфигурации JSON (по умолчанию: ~/{APP_NAME_FOR_CONFIG}/{DEFAULT_CONFIG_FILENAME}).")
    table.add_row("  --update-config", "Обновить файл конфигурации по умолчанию значениями из CLI (кроме API ключа и пути к изображению).")
    table.add_row("  --api-key KEY", "API ключ Google Cloud (переопределяет значение из конфига).")
    table.add_row("  --proxy URL", "URL прокси-сервера (например, http://user:pass@host:port).")
    table.add_row("  --timeout SECONDS", "Таймаут для HTTP запросов в секундах (по умолчанию: 60).")
    table.add_row("  --font FONT_PATH", "Путь к файлу шрифта .ttf для наложения текста.")
    table.add_row("  --font-size SIZE", "Размер шрифта для наложения (по умолчанию: 20).")
    table.add_row("  --client-region REGION", f"Код региона клиента (CLDR, по умолчанию: '{DEFAULT_CLIENT_REGION}').")
    table.add_row("  --client-time-zone TZ", f"Часовой пояс клиента (CLDR, по умолчанию: '{DEFAULT_CLIENT_TIME_ZONE}').")
    table.add_row("")
    table.add_row("[bold]Отладка и помощь:[/bold]")
    table.add_row("  -l, --logging-level LEVEL", "Уровень логирования (DEBUG, INFO, WARNING, ERROR). По умолчанию: WARNING.")
    table.add_row("  -h, --help", "Показать это сообщение и выйти.")
    
    console.print(table)
    console.print("\nПример (OCR японский, перевод на русский): lens_scan /path/to/image.png ja -t ru -to /path/to/output.png")
    console.print("Пример (Автоопределение OCR, перевод на английский): lens_scan /path/to/image.png -t en")


async def cli_main():
    parser = argparse.ArgumentParser(description="Google Lens CLI", add_help=False)
    
    parser.add_argument("image_path", nargs="?", help="Путь к файлу изображения.")
    parser.add_argument(
        "ocr_lang", 
        nargs="?", 
        default=None, # Будет None если ocr_lang не указан пользователем
        help="BCP 47 код языка для OCR (автоопределение если не указан)."
    )

    parser.add_argument("-t", "--translate", dest="target_lang", help="Целевой язык для перевода.")
    parser.add_argument("--translate-from", dest="source_lang", help="Исходный язык для перевода (автоопределение если не указан).")
    parser.add_argument("-to", "--translate-out", dest="output_overlay_path", help="Путь для сохранения изображения с наложенным переводом.")

    parser.add_argument("--config-file", dest="config_file_path_override", help="Путь к файлу конфигурации.")
    parser.add_argument("--update-config", action="store_true", help="Обновить файл конфигурации значениями из CLI.")
    parser.add_argument("--api-key", help="API ключ Google Cloud.")
    parser.add_argument("--proxy", help="URL прокси-сервера.")
    parser.add_argument("--timeout", type=int, help="Таймаут для HTTP запросов (секунды).")
    parser.add_argument("--font", dest="font_path", help="Путь к файлу шрифта .ttf.")
    parser.add_argument("--font-size", type=int, help="Размер шрифта для наложения.")
    parser.add_argument("--client-region", help="Код региона клиента (CLDR).")
    parser.add_argument("--client-time-zone", help="Часовой пояс клиента (CLDR).")

    parser.add_argument("-l", "--logging-level", dest="logging_level", help="Уровень логирования (DEBUG, INFO, WARNING, ERROR).")
    parser.add_argument("-h", "--help", action="store_true", help="Показать справку.")

    args = parser.parse_args()

    if args.help:
        print_help()
        sys.exit(0)

    if not args.image_path: # ocr_lang теперь может быть None
        console.print("[bold red]Ошибка:[/bold red] Необходимо указать `image_path`.\n")
        print_help()
        sys.exit(1)

    cli_config_args = {k: v for k, v in vars(args).items() if v is not None and k not in ['help', 'update_config']}
    # Если ocr_lang не был указан пользователем (args.ocr_lang is None), то в cli_config_args он не попадет,
    # и build_app_config возьмет его из конфиг файла или DEFAULT_OCR_LANG.
    # Если пользователь явно указал ocr_lang (даже пустую строку для авто), он попадет в cli_config_args.
    # Это поведение можно изменить, если мы хотим, чтобы "не указан ocr_lang" всегда означало авто.
    # Текущая логика: если args.ocr_lang is None, то build_app_config использует config/default.
    # Если мы хотим, чтобы args.ocr_lang=None всегда означало авто, нужно это явно передать.
    # Давайте сделаем так:
    if 'ocr_lang' not in cli_config_args and args.ocr_lang is None:
         # Если пользователь не указал ocr_lang, это сигнал для автоопределения,
         # поэтому передаем DEFAULT_OCR_LANG (который "") в build_app_config
         cli_config_args['ocr_lang'] = DEFAULT_OCR_LANG
    elif args.ocr_lang is not None: # Пользователь явно указал ocr_lang
         cli_config_args['ocr_lang'] = args.ocr_lang


    app_config = build_app_config(cli_args=cli_config_args, config_file_path_override=args.config_file_path_override)
    setup_logging(app_config.get("logging_level", "WARNING"))

    if not is_image_file_supported(args.image_path):
        console.print(f"[bold red]Ошибка:[/bold red] Файл '{args.image_path}' не является поддерживаемым изображением или не найден.")
        sys.exit(1)

    if args.update_config:
        config_update_cli_args = {
            k: v for k, v in vars(args).items() 
            if v is not None and k in [
                "api_key", "client_region", "client_time_zone", "proxy", 
                "timeout", "font_path", "font_size", "logging_level",
                # "ocr_lang" - если мы хотим, чтобы он тоже сохранялся в конфиг
            ]
        }
        # Если ocr_lang был None (пользователь не указал), но мы хотим сохранить дефолтное значение автоопределения
        if args.ocr_lang is None and 'ocr_lang' not in config_update_cli_args:
            config_update_cli_args['ocr_lang'] = DEFAULT_OCR_LANG # Сохраняем "" в конфиг

        try:
            update_config_file_from_cli(config_update_cli_args, args.config_file_path_override)
            console.print(f"Файл конфигурации '{get_config_file_path(args.config_file_path_override)}' обновлен (если были изменения).")
        except Exception as e:
            console.print(f"[bold red]Ошибка при обновлении конфигурации:[/bold red] {e}")

    api = LensAPI(
        api_key=app_config["api_key"],
        client_region=app_config["client_region"],
        client_time_zone=app_config["client_time_zone"],
        proxy=app_config.get("proxy"),
        timeout=app_config.get("timeout", 60),
        font_path=app_config.get("font_path"),
        font_size=app_config.get("font_size")
    )

    try:
        console.print(f"Обработка изображения: [cyan]{args.image_path}[/cyan]...")
        # app_config["ocr_lang"] теперь будет содержать значение из CLI (если было), 
        # или из файла конфига (если там есть), или DEFAULT_OCR_LANG.
        # Если пользователь не указал ocr_lang в CLI, и в конфиге его нет,
        # то app_config["ocr_lang"] будет DEFAULT_OCR_LANG (т.е. "").
        ocr_lang_for_api = app_config.get("ocr_lang", DEFAULT_OCR_LANG) # Гарантируем, что передаем строку

        result = await api.process_image(
            image_path=args.image_path,
            ocr_language=ocr_lang_for_api,
            target_translation_language=args.target_lang,
            source_translation_language=args.source_lang,
            output_overlay_path=args.output_overlay_path
        )

        console.print("\n[bold green]Результаты OCR:[/bold green]")
        console.print(Text(result.get("ocr_text", "Нет OCR текста.")))

        translated_text_value = result.get("translated_text")
        if translated_text_value is not None:
            console.print("\n[bold green]Переведенный текст:[/bold green]")
            console.print(Text(translated_text_value)) # Здесь мы уверены, что это строка
        elif args.target_lang:
            console.print("\n[yellow]Перевод не был получен (возможно, ошибка или не поддерживается пара языков).[/yellow]")
            

        if args.output_overlay_path:
            if result.get("translated_text"):
                 console.print(f"\nИзображение с наложением сохранено в: [cyan]{args.output_overlay_path}[/cyan]")
            else:
                 console.print(f"\n[yellow]Изображение с наложением НЕ сохранено, так как отсутствует переведенный текст.[/yellow]")

    except LensException as e:
        console.print(f"\n[bold red]Ошибка API Lens:[/bold red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Непредвиденная ошибка:[/bold red] {e}")
        logging.exception("An unexpected error occurred in CLI.")
        sys.exit(1)

def run():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(cli_main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Операция прервана пользователем.[/yellow]")
        sys.exit(130)

if __name__ == "__main__":
    run()