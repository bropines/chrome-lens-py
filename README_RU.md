# Chrome Lens API для Python

[English](/README.md) | **Русский**

[![PyPI version](https://badge.fury.io/py/chrome-lens-py.svg)](https://badge.fury.io/py/chrome-lens-py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/pypi/pyversions/chrome-lens-py.svg)](https://pypi.org/project/chrome-lens-py)
[![Downloads](https://static.pepy.tech/badge/chrome-lens-py)](https://pepy.tech/project/chrome-lens-py)

> [!IMPORTANT]
> **Масштабное обновление (Версия 3.1.0+)**
> Библиотека была полностью переписана с нуля. Теперь она использует современную асинхронную архитектуру (`async`/`await`) и взаимодействует напрямую с Protobuf эндпоинтом Google для значительно улучшенной надежности и производительности.
>
> **Пожалуйста, обновите ваши проекты. Все вызовы API теперь являются `async`.**

> [!Warning]
> Также обратите внимание, что библиотека была полностью переписана, и я мог что-то пропустить или не указать. Если вы заметили ошибку, сообщите мне в разделе "Issues"

Этот проект предоставляет мощную, асинхронную Python-библиотеку и утилиту командной строки для взаимодействия с Google Lens. Она позволяет выполнять продвинутое распознавание текста (OCR), получать сегментированные текстовые блоки (например, для комиксов), переводить текст и получать точные координаты слов.

## 🚀 Быстрый старт для пользователей Windows

Если вы не хотите устанавливать Python, вы можете скачать готовый файл **lens_scan-windows-amd64.exe** из раздела [Releases](https://github.com/bropines/chrome-lens-py/releases).

> [!WARNING]
> **Ложные срабатывания антивируса**: Некоторые антивирусы (например, Windows Defender) могут помечать скомпилированный `.exe` как угрозу (например, `Trojan:Win32/Wacatac.H!ml`). Это **ложное срабатывание**, характерное для бинарных файлов Nuitka/PyInstaller. Проект имеет открытый исходный код; вы можете изучить его и собрать файл самостоятельно, если у вас есть сомнения.

### 📸 Автоматическая настройка ShareX
Если вы используете **ShareX**, вы можете полностью автоматизировать настройку одной командой:
```bash
# Через установленный пакет:
lens_scan --setup-sharex

# Или через готовый .exe файл:
lens_scan-windows-amd64.exe --setup-sharex
```
Это автоматически настроит горячую клавишу (**Ctrl + O**) и все необходимые действия для использования Google Lens OCR.

---

## ✨ Ключевые возможности

-   **Современный бэкенд**: Использует официальный Protobuf-эндпоинт (`v1/crupload`) Google для получения надежных и точных результатов.
-   **Асинхронность и безопасность**: Построена на `asyncio` и `httpx`. Включает встроенный семафор для предотвращения злоупотреблений API и банов IP-адресов из-за чрезмерного количества одновременных запросов.
-   **Мощный OCR и сегментация**:
    -   Извлекайте текст с изображений в виде единой строки.
    -   Получайте текст, разделенный на логические блоки (абзацы, диалоговые окна) с их собственными координатами.
    -   Получайте отдельные строки текста с их собственной точной геометрией.
-   **Встроенный перевод**: Мгновенно переводите распознанный текст на любой поддерживаемый язык.
-   **Разные источники изображений**: Обрабатывайте изображения из **файла**, по **URL**, из **байтов**, объекта **PIL Image** или массива **NumPy**.
-   **Наложение текста**: Автоматически генерируйте и сохраняйте изображения с наложенным на них переводом(работает плохо, увы нет времени сделать лучше).
-   **Функциональный CLI**: Простой, но мощный интерфейс командной строки (`lens_scan`) для быстрого использования.
-   **Поддержка прокси**: Полная поддержка HTTP, HTTPS и SOCKS прокси.
-   **Интеграция с буфером обмена**: Мгновенно копируйте результаты OCR или перевода в буфер обмена с помощью флага `--sharex`.
-   **Гибкая конфигурация**: Управляйте настройками через файл `config.json`, аргументы CLI или переменные окружения.

## 🚀 Установка

Вы можете установить пакет с помощью `pip`:

```bash
pip install chrome-lens-py
```

Чтобы включить функцию копирования в буфер обмена (флаг `--sharex`), установите библиотеку с `[clipboard]` extra:

```bash
pip install "chrome-lens-py[clipboard]"
```

Или установите последнюю версию напрямую с GitHub:
```bash
pip install git+https://github.com/bropines/chrome-lens-py.git
```
## 🚀 Использование


<details>
  <summary><b>🛠️ Использование CLI (`lens_scan`)</b></summary>

  Утилита командной строки предоставляет быстрый доступ к возможностям библиотеки прямо из вашего терминала.

  ```bash
  lens_scan <источник_изображения> [язык_ocr] [опции]
  ```

  -   **`<источник_изображения>`**: Путь к локальному файлу или URL-адрес изображения.
  -   **`[язык_ocr]`** (опционально): Код языка в формате BCP 47 для OCR (например, 'en', 'ja'). Если не указан, API попытается определить язык автоматически.

  #### **Опции**

| Флаг | Алиас | Описание |
| :--- | :--- | :--- |
| `--translate <язык>` | `-t` | **Перевести** распознанный текст на целевой язык (например, `en`, `ru`). |
| `--translate-from <язык>` | | Указать исходный язык для перевода (иначе определяется автоматически). |
| `--translate-out <путь>` | `-to` | **Сохранить** изображение с наложенным переводом по указанному пути. |
| `--output-blocks` | `-b` | **Вывести текст OCR в виде сегментированных блоков** (полезно для комиксов). Несовместимо с `--get-coords` и `--output-lines`.|
| `--output-lines` | `-ol` | **Вывести текст OCR в виде отдельных строк** с их геометрией. Несовместимо с `--output-blocks` и `--get-coords`.|
| `--get-coords` | | Вывести распознанные слова и их координаты в формате JSON. Несовместимо с `--output-blocks` и `--output-lines`.|
| `--sharex` | `-sx` | **Скопировать** результат в буфер обмена (перевод или OCR). |
| `--ocr-single-line` | | Объединить весь распознанный текст в одну строку, удалив переносы. |
| `--config-file <путь>`| | Путь к кастомному файлу конфигурации в формате JSON. |
| `--update-config` | | Обновить файл конфигурации по умолчанию настройками из текущей команды. |
| `--font <путь>` | | Путь к файлу шрифта `.ttf` для наложения текста. |
| `--font-size <размер>` | | Размер шрифта для наложения (по умолчанию: 20). |
| `--proxy <url>` | | URL прокси-сервера (например, `socks5://127.0.0.1:9050`). |
| `--logging-level <ур>`| `-l` | Установить уровень логирования (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `--help` | `-h` | Показать это справочное сообщение. |

  #### **Примеры**

  **1. Базовое распознавание (OCR) и перевод**
  
  Автоматически определяет язык на изображении и переводит его на английский. Это самый распространенный сценарий использования.
  ```bash
  lens_scan "путь/к/вашему/изображению.png" -t en
  ```

  ---
  
  **2. Получение сегментированных текстовых блоков (для комиксов/манги)**

  Идеально подходит для изображений с несколькими отдельными текстовыми блоками. Эта команда выводит каждый распознанный блок текста по отдельности, что отлично подходит для перевода комиксов или сложных документов.
  ```bash
  lens_scan "путь/к/манге.jpg" ja -b
  ```
  - `-b` — это короткий псевдоним для `--output-blocks`.

  ---
  
  **3. Получение отдельных строк текста**
  
  Выводит каждую распознанную строку текста вместе с ее геометрией.
  ```bash
  lens_scan "путь/к/документу.png" --output-lines
  ```
  - `-ol` — это короткий псевдоним для `--output-lines`.
  
  ---

  **4. Получение координат всех отдельных слов**
  
  Выводит подробный массив JSON, содержащий каждое распознанное слово и его точные геометрические данные (центр, размер, угол). Полезно для программного анализа или создания собственных наложений.
  ```bash
  lens_scan "путь/к/схеме.png" --get-coords
  ```
  
  ---

  **5. Перевести, сохранить с наложением и скопировать в буфер обмена**
  
  Пример для продвинутых пользователей. Эта команда выполнит несколько действий:
  1. Распознает текст на японском изображении.
  2. Переведет его на русский.
  3. Сохранит новое изображение `перевод_манги.png` с наложенным на него русским текстом.
  4. Скопирует итоговый перевод в буфер обмена.
  ```bash
  lens_scan "путь/к/манге.jpg" ja -t ru -to "перевод_манги.png" -sx
  ```

  ---

  **6. Обработать изображение по URL и получить текст в одну строку**

  Загружает изображение напрямую по URL-адресу и объединяет весь распознанный текст в одну непрерывную строку, удаляя все переносы.
  ```bash
  lens_scan "https://i.imgur.com/VPd1y6b.png" en --ocr-single-line
  ```

  ---

  **7. Использовать SOCKS5 прокси**
  
  Все запросы к API Google будут направляться через указанный прокси-сервер, что полезно для обеспечения конфиденциальности или обхода региональных ограничений.
  ```bash
  lens_scan "image.png" --proxy "socks5://127.0.0.1:9050"
  ```


</details>

<details>
  <summary><b>👨‍💻 Программное использование (API)</b></summary>
  
  > [!IMPORTANT]
  > `LensAPI` полностью **асинхронный**. Все методы для получения данных должны вызываться с помощью `await` из `async` функции.

  #### **Базовый пример (Полный текст)**
  
  ```python
  import asyncio
  from chrome_lens_py import LensAPI

  async def main():
      # Инициализируем API. Здесь можно передать прокси, регион и т.д.
      # По умолчанию API ключ не требуется.
      api = LensAPI()

      image_source = "путь/к/вашему/изображению.png" # Или URL, PIL Image, NumPy array

      try:
          # Обрабатываем изображение и получаем текст единой строкой
          result = await api.process_image(
              image_path=image_source,
              ocr_language="ja",
              target_translation_language="en"
          )

          print("--- Распознанный текст (OCR) ---")
          print(result.get("ocr_text"))

          print("\n--- Переведенный текст ---")
          print(result.get("translated_text"))
          
      except Exception as e:
          print(f"Произошла ошибка: {e}")

  if __name__ == "__main__":
      asyncio.run(main())
  ```

  #### **Работа с разными источниками изображений**

  Метод `process_image` легко обрабатывает различные типы входных данных.

  ```python
  from PIL import Image
  import numpy as np

  # ... внутри async функции ...
  
  # Из URL
  result_url = await api.process_image("https://i.imgur.com/VPd1y6b.png")

  # Из объекта PIL Image
  with Image.open("путь/к/изображению.png") as img:
      result_pil = await api.process_image(img)

  # Из массива NumPy (например, загруженного через OpenCV)
  with Image.open("путь/к/изображению.png") as img:
      numpy_array = np.array(img)
      result_numpy = await api.process_image(numpy_array)
  ```
  
  #### **Получение сегментированных текстовых блоков**

  Чтобы получить текст, разделенный на логические блоки (например, диалоговые окна в комиксе), используйте параметр `output_format='blocks'`.

  ```python
  import asyncio
  from chrome_lens_py import LensAPI

  async def process_comics():
      api = LensAPI()
      image_source = "путь/к/манге.jpg"
      
      result = await api.process_image(
          image_path=image_source,
          output_format='blocks' # Получить сегментированные блоки вместо одной строки
      )

      # Результат теперь содержит ключ 'text_blocks'
      text_blocks = result.get("text_blocks", [])
      print(f"Найдено {len(text_blocks)} текстовых блоков.")

      for i, block in enumerate(text_blocks):
          print(f"\n--- Блок #{i+1} ---")
          print(block['text'])
          # block также содержит ключи 'lines' и 'geometry'
  
  asyncio.run(process_comics())
  ```

  #### **Получение отдельных строк и их геометрии**

  Чтобы получить каждую распознанную строку текста как отдельный элемент, используйте параметр `output_format='lines'`.

  ```python
  import asyncio
  from chrome_lens_py import LensAPI

  async def process_document_lines():
      api = LensAPI()
      image_source = "путь/к/документу.png"
      
      result = await api.process_image(
          image_path=image_source,
          output_format='lines' # Получить отдельные строки с их геометрией
      )

      # Результат теперь содержит ключ 'line_blocks'
      line_blocks = result.get("line_blocks", [])
      print(f"Найдено {len(line_blocks)} строк.")

      for i, line in enumerate(line_blocks):
          print(f"\n--- Строка #{i+1} ---")
          print(f"Текст: {line['text']}")
          print(f"Геометрия: {line['geometry']}")
  
  asyncio.run(process_document_lines())
  ```
#### **Получение полностью детализированных структур текста**

Чтобы получить полную, вложенную структуру из абзацев, строк и слов с геометрией на каждом уровне, используйте `output_format='detailed'`.

```python
import asyncio
from chrome_lens_py import LensAPI

async def process_with_details():
    api = LensAPI()
    image_source = "путь/к/документу.png"
    
    result = await api.process_image(
        image_path=image_source,
        output_format='detailed' # Получить полностью вложенную структуру
    )

    # Результат теперь содержит ключ 'detailed_blocks'
    detailed_blocks = result.get("detailed_blocks", [])
    print(f"Найдено {len(detailed_blocks)} детализированных блоков.")

    for i, block in enumerate(detailed_blocks):
        print(f"\n--- Блок #{i+1} ---")
        print(f"  Геометрия: {block['geometry']}")
        for j, line in enumerate(block['lines']):
            print(f"    --- Строка #{j+1}: '{line['text']}' ---")
            for k, word in enumerate(line['words']):
                 print(f"      - Слово: '{word['text']}', Геометрия: {word['geometry']}")

asyncio.run(process_with_details())
```


  #### **Конструктор `LensAPI`**

  ```python
  api = LensAPI(
      api_key: str = "ВАШ_API_КЛЮЧ_ИЛИ_КЛЮЧ_ПО_УМОЛЧАНИЮ",
      client_region: Optional[str] = None,
      client_time_zone: Optional[str] = None,
      proxy: Optional[str] = None,
      timeout: int = 60,
      font_path: Optional[str] = None,
      font_size: Optional[int] = None,
      max_concurrent: int = 5
  )
  ```

  #### **Метод `process_image`**
  
  ```python
  result: dict = await api.process_image(
      image_path: Any,
      ocr_language: Optional[str] = None,
      target_translation_language: Optional[str] = None,
      source_translation_language: Optional[str] = None,
      output_overlay_path: Optional[str] = None,
      ocr_preserve_line_breaks: bool = True,
      output_format: Literal['full_text', 'blocks', 'lines', 'detailed'] = 'full_text''
  )
  ```
  -   **`output_format`**: Управляет структурой OCR-вывода. `'full_text'` (по умолчанию) возвращает одну строку в `ocr_text`. `'blocks'` возвращает список в `text_blocks`. `'lines'` возвращает список в `line_blocks`. `'detailed'` возвращает полностью вложенную структуру в `detailed_blocks`.`
  -   **`ocr_preserve_line_breaks`**: Если `False` и `output_format` равен `'full_text'`, объединяет весь текст OCR в одну строку.

  **Возвращаемый словарь `result` содержит:**
  - `ocr_text` (Optional[str]): Полный распознанный текст (если `output_format='full_text'`).
  - `text_blocks` (Optional[List[dict]]): Список сегментированных текстовых блоков (если `output_format='blocks'`). Каждый блок — это словарь с ключами `text`, `lines` и `geometry`.
  - `line_blocks` (Optional[List[dict]]): Список отдельных текстовых строк (если `output_format='lines'`). Каждый блок — это словарь с ключами `text` и `geometry`.
  - `translated_text` (Optional[str]): Переведенный текст, если был запрошен.
  - `word_data` (List[dict]): Список словарей для каждого распознанного слова с его геометрией.
  - `detailed_blocks` (Optional[List[dict]]): Список полностью структурированных текстовых блоков (если `output_format='detailed'`). Каждый блок содержит строки, которые, в свою очередь, содержат слова, с геометрией на каждом уровне.
  - `raw_response_objects`: "Сырой" Protobuf-объект ответа для дальнейшего анализа.

</details>

<details>
  <summary><b>⚙️ Конфигурация</b></summary>
  
  Настройки загружаются со следующим приоритетом: **Аргументы CLI > Файл `config.json` > Значения по умолчанию**.
  
  #### **`config.json`**
  
  Файл `config.json` можно разместить в директории конфигурации по умолчанию вашей ОС для установки постоянных опций.
  -   **Linux**: `~/.config/chrome-lens-py/config.json`
  -   **macOS**: `~/Library/Application Support/chrome-lens-py/config.json`
  -   **Windows**: `C:\Users\<user>\.config\chrome-lens-py\config.json`

  ##### **Пример `config.json`**
  ```json
  {
    "api_key": "ОПЦИОНАЛЬНО! Если вы не знаете что это, то не советую его здесь указывать",
    "proxy": "socks5://127.0.0.1:9050",
    "client_region": "DE",
    "client_time_zone": "Europe/Berlin",
    "timeout": 90,
    "font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "ocr_preserve_line_breaks": true
  }
  ```

</details>

## Интеграция Sharex
Посмотрите [sharex.md](docs/sharex.md) для получения дополнительной информации о том, как использовать эту библиотеку с ShareX.

## ❤️ Поддержка и благодарности

-   **OWOCR**: В большей степени вдохновлен и основан на [OWOCR](https://github.com/AuroraWright/owocr). Благодарю ребят, за их ресерч protobuf и реализацию OCR.
-   **Chrome Lens OCR**: За изначальную реализацию и идеи, которые легли в основу этой библиотеки. Обновление с поддержкой SHAREX изначально было протестировано и добавлено мной в [chrome-lens-ocr](https://github.com/dimdenGD/chrome-lens-ocr), спасибо за изначальную реализацию и идеи.
-   **Совместная работа с ИИ**: Значительная часть кода версии 3.0, включая рефакторинг архитектуры, асинхронную реализацию и интеграцию с Protobuf, была разработана в сотрудничестве с продвинутым ИИ-ассистентом.
-   **GOOGLE**: За удобную и качественную технологию Lens.
-   **Поддержать автора**: Если эта библиотека оказалась вам полезной, вы можете поддержать автора - **[Boosty](https://boosty.to/pinus)**

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bropines/chrome-lens-py&type=Date)](https://www.star-history.com/#bropines/chrome-lens-py&Date)

### Отказ от ответственности

Этот проект предназначен исключительно для образовательных и экспериментальных целей. Использование сервисов Google должно соответствовать их Условиям предоставления услуг. Автор проекта не несет ответственности за любое неправомерное использование этого программного обеспечения.