# back/myproject/myapp/pdftoexcel.py
import json
import logging
import os
import tempfile
from datetime import datetime
from io import BytesIO

import pandas as pd
import pdfplumber
from django.http import FileResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser

logger = logging.getLogger(__name__)

@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def convert_pdf_to_excel(request):
    try:
        pdf_file = request.FILES.get('pdf_file')
        if not pdf_file:
            return JsonResponse({'success': False, 'error': 'No PDF file provided.'}, status=400)

        settings = request.POST.get('settings', '{}')
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError:
            settings = {}

        extract_tables = settings.get('extractTables', True)
        # Placeholder for other settings like extractText, preserveFormatting, detectHeaders

        output_format = settings.get('outputFormat', 'xlsx')

        all_tables_data = []

        with pdfplumber.open(BytesIO(pdf_file.read())) as pdf:
            for page in pdf.pages:
                if extract_tables:
                    tables = page.extract_tables()
                    for table in tables:
                        # Convert each table to a DataFrame and append
                        df = pd.DataFrame(table[1:], columns=table[0]) if table and table[0] else pd.DataFrame(table)
                        all_tables_data.append(df)
                # else:
                #     # Basic text extraction if not extracting tables
                #     text = page.extract_text()
                #     if text:
                #         all_tables_data.append(pd.DataFrame([text.splitlines()]))

        if not all_tables_data:
            return JsonResponse({'success': False, 'error': 'No tables or extractable data found in PDF.'}, status=400)

        # Combine all extracted data into a single Excel file, each DataFrame as a separate sheet
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            for i, df in enumerate(all_tables_data):
                df.to_excel(writer, sheet_name=f'Table_{i+1}', index=False)
        excel_buffer.seek(0)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{pdf_file.name.split(".")[0]}_{timestamp}.{output_format}'

        response = FileResponse(
            excel_buffer,
            content_type=f'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if output_format == 'xlsx' else 'application/vnd.ms-excel',
            as_attachment=True,
            filename=filename
        )
        response['Content-Length'] = excel_buffer.getbuffer().nbytes
        response['Access-Control-Expose-Headers'] = 'Content-Disposition'
        return response

    except Exception as e:
        logger.error(f"Error converting PDF to Excel: {e}")
        return JsonResponse({'success': False, 'error': f'Failed to convert PDF to Excel: {e}'}, status=500)
