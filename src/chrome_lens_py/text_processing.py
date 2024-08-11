# text_processing.py

import re

def stitch_text_from_coordinates(text_with_coords):
    """Сшивает текст из координат по строкам и позициям."""
    sorted_elements = sorted(text_with_coords, key=lambda x: (round(x['coordinates'][1], 2), x['coordinates'][0]))

    stitched_text = ""
    current_y = None
    current_line = []

    for element in sorted_elements:
        if current_y is None or abs(element['coordinates'][1] - current_y) > 0.05:
            if current_line:
                stitched_text += " ".join(current_line) + "\n"
                current_line = []
            current_y = element['coordinates'][1]
        current_line.append(element['text'])

    if current_line:
        stitched_text += " ".join(current_line)

    stitched_text = re.sub(r'\s+([,?.!])', r'\1', stitched_text)

    return stitched_text.strip()

def stitch_text_smart(text_with_coords):
    """Сшивает текст из координат умным методом."""
    transformed_coords = [{'text': item['text'], 'coordinates': [item['coordinates'][1], item['coordinates'][0]]} for item in text_with_coords]
    sorted_elements = sorted(transformed_coords, key=lambda x: (round(x['coordinates'][1], 2), x['coordinates'][0]))

    stitched_text = []
    current_y = None
    current_line = []
    word_threshold = 0.02

    for element in sorted_elements:
        if current_y is None or abs(element['coordinates'][1] - current_y) > 0.05:
            if current_line:
                stitched_text.append(" ".join(current_line))
                current_line = []
            current_y = element['coordinates'][1]

        if element['text'] in [',', '.', '!', '?', ';', ':'] and current_line:
            current_line[-1] += element['text']
        else:
            current_line.append(element['text'])

    if current_line:
        stitched_text.append(" ".join(current_line))

    return "\n".join(stitched_text).strip()

def stitch_text_sequential(text_with_coords):
    """Сшивает текст в последовательности, как он был распознан."""
    stitched_text = " ".join([element['text'] for element in text_with_coords])
    stitched_text = re.sub(r'\s+([,?.!])', r'\1', stitched_text)
    
    return stitched_text.strip()

def extract_text_and_coordinates(data):
    """Извлекает текст и координаты из структуры данных."""
    text_with_coords = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, list):
                for sub_item in item:
                    if isinstance(sub_item, list) and len(sub_item) > 1 and isinstance(sub_item[0], str):
                        word = sub_item[0]
                        coords = sub_item[1]
                        if isinstance(coords, list) and all(isinstance(coord, (int, float)) for coord in coords):
                            text_with_coords.append({"text": word, "coordinates": coords})
                    else:
                        text_with_coords.extend(extract_text_and_coordinates(sub_item))
            else:
                text_with_coords.extend(extract_text_and_coordinates(item))
    elif isinstance(data, dict):
        for value in data.values():
            text_with_coords.extend(extract_text_and_coordinates(value))
    return text_with_coords

def extract_full_text(data):
    """Извлекает полный текст из структуры данных."""
    try:
        text_data = data[3][4][0][0]
        if isinstance(text_data, list):
            return "\n".join(text_data)
        return text_data
    except (IndexError, TypeError):
        return "Full text not found in expected structure"

def simplify_output(result):
    """Упрощает структуру данных, извлекая ключевые элементы."""
    simplified = {}
    
    try:
        if 'data' in result and isinstance(result['data'], list) and len(result['data']) > 3:
            if isinstance(result['data'][3], list) and len(result['data'][3]) > 3:
                simplified['language'] = result['data'][3][3]
            else:
                simplified['language'] = "Language not found in expected structure"
        
        simplified['full_text'] = extract_full_text(result['data'])
        
        if 'data' in result and isinstance(result['data'], list):
            text_with_coords = extract_text_and_coordinates(result['data'])
            simplified['text_with_coordinates'] = text_with_coords
            
            simplified['stitched_text_smart'] = stitch_text_smart(text_with_coords)
            simplified['stitched_text_sequential'] = stitch_text_sequential(text_with_coords)
    except Exception as e:
        print(f"Error in simplify_output: {e}")
        simplified['error'] = str(e)
    
    return simplified
