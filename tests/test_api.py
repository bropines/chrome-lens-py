import pytest
from chrome_lens_py import LensAPI
from chrome_lens_py.exceptions import LensException

@pytest.mark.asyncio
async def test_ocr_functionality():
    api = LensAPI()
    # Using the valid image from test_base.py
    image_url = "https://avatars.mds.yandex.net/get-kinopoisk-image/4303601/9e44389e-0205-433d-9bca-d90a8bea0a32/1200x630"
    
    try:
        result = await api.process_image(image_url, ocr_language="en")
        assert "ocr_text" in result
        assert len(result["ocr_text"]) > 0
        assert "word_data" in result
    except LensException as e:
        pytest.fail(f"OCR test failed with LensException: {e}")

@pytest.mark.asyncio
async def test_translation_functionality():
    api = LensAPI()
    image_url = "https://avatars.mds.yandex.net/get-kinopoisk-image/4303601/9e44389e-0205-433d-9bca-d90a8bea0a32/1200x630"
    
    try:
        result = await api.process_image(image_url, target_translation_language="en")
        assert "translated_text" in result
        assert result["translated_text"] is not None
    except LensException as e:
        pytest.fail(f"Translation test failed with LensException: {e}")

@pytest.mark.asyncio
async def test_output_formats():
    api = LensAPI()
    image_url = "https://avatars.mds.yandex.net/get-kinopoisk-image/4303601/9e44389e-0205-433d-9bca-d90a8bea0a32/1200x630"
    
    # Test blocks
    result_blocks = await api.process_image(image_url, output_format="blocks")
    assert "text_blocks" in result_blocks
    
    # Test lines
    result_lines = await api.process_image(image_url, output_format="lines")
    assert "line_blocks" in result_lines
    
    # Test detailed
    result_detailed = await api.process_image(image_url, output_format="detailed")
    assert "detailed_blocks" in result_detailed
