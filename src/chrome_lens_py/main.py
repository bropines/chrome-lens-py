import sys
import argparse
import logging
from .lens_api import LensAPI
from rich.console import Console
from .exceptions import LensAPIError, LensParsingError, LensCookieError

console = Console()

def print_help():
    console.print("Usage: [b]lens_scan [options] <image_source> <data_type>[/b]")
    console.print("\nOptions:")
    console.print("[b]-h, --help[/b]                Show this help message and exit")
    console.print("[b]-c, --cookie-file[/b]         Path to the Netscape cookie file")
    console.print("[b]-p, --proxy[/b]               Specify proxy server (e.g., socks5://user:pass@host:port)")
    console.print("[b]--debug=(info|debug)[/b]      Enable logging at the specified level")
    console.print("[b]--coordinate-format[/b]       Output coordinates format: 'percent' or 'pixels'")
    console.print("\n[b]<data_type>[/b] options:")
    console.print("[b]all[/b]                       Get all data (full text, coordinates, and stitched text)")
    console.print("[b]full_text_default[/b]         Get only the default full text")
    console.print("[b]full_text_old_method[/b]      Get stitched text using the old method")
    console.print("[b]full_text_new_method[/b]      Get stitched text using the new method")
    console.print("[b]coordinates[/b]               Get text with coordinates")

def main():
    parser = argparse.ArgumentParser(
        description="Process images with Google Lens API and extract text data.", add_help=False)
    parser.add_argument('image_source', nargs='?', help="Path to the image file or URL")
    parser.add_argument('data_type', nargs='?', choices=[
        'all', 'full_text_default', 'full_text_old_method', 'full_text_new_method', 'coordinates'], help="Type of data to extract")
    parser.add_argument('-h', '--help', action='store_true',
                        help="Show this help message and exit")
    parser.add_argument('-c', '--cookie-file',
                        help="Path to the Netscape cookie file")
    parser.add_argument(
        '-p', '--proxy', help="Proxy server (e.g., socks5://user:pass@host:port)")
    parser.add_argument('--debug', choices=['info', 'debug'],
                        help="Enable logging at the specified level")
    # Добавляем аргумент для выбора формата координат
    parser.add_argument('--coordinate-format', choices=['percent', 'pixels'], default='percent',
                        help="Output coordinates format: 'percent' or 'pixels'")

    args = parser.parse_args()

    if args.help or not args.image_source or not args.data_type:
        print_help()
        sys.exit(1)

    # Настраиваем уровень логирования на основе параметра debug
    if args.debug == 'debug':
        logging_level = logging.DEBUG
    elif args.debug == 'info':
        logging_level = logging.INFO
    else:
        logging_level = logging.WARNING

    logging.basicConfig(level=logging_level)

    config = {}
    if args.cookie_file:
        config['headers'] = {'cookie': args.cookie_file}
    if args.proxy:
        config['proxy'] = args.proxy

    # Передаем уровень логирования в LensAPI
    api = LensAPI(config=config, logging_level=logging_level)

    image_source = args.image_source
    data_type = args.data_type
    coordinate_format = args.coordinate_format  # Получаем формат координат из аргументов

    try:
        if data_type == "all":
            result = api.get_all_data(image_source, coordinate_format=coordinate_format)
        elif data_type == "full_text_default":
            result = api.get_full_text(image_source)
        elif data_type == "full_text_old_method":
            result = api.get_stitched_text_sequential(image_source, coordinate_format=coordinate_format)
        elif data_type == "full_text_new_method":
            result = api.get_stitched_text_smart(image_source, coordinate_format=coordinate_format)
        elif data_type == "coordinates":
            result = api.get_text_with_coordinates(image_source, coordinate_format=coordinate_format)
        else:
            console.print("[red]Invalid data type specified.[/red]")
            sys.exit(1)

        # Выводим результат
        console.print(result)

    except (LensAPIError, LensParsingError, LensCookieError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
