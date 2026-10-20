"""Reproducible 16:9 submission deck, with explicit verification boundaries."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output'/'pdf'/'CampusPulse_GDG_Astana.pdf'


def main():
    pdfmetrics.registerFont(TTFont('Arial','C:/Windows/Fonts/arial.ttf'))
    pdfmetrics.registerFont(TTFont('ArialBold','C:/Windows/Fonts/arialbd.ttf'))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    deck=canvas.Canvas(str(OUT),pagesize=(960,540))
    deck.setTitle('CampusPulse AI | GDG Astana')
    slides=[
      ('CampusPulse AI','Учебный план, который опирается на твои данные.',[
        'GDG Astana · Smart Autonomous Agent with MCP',
        'Gemini / Vertex AI · MCP · Firestore · Agent Engine',
        'Запрос студента → проверенные данные → план → подтверждённое действие']),
      ('Проблема студента','Дедлайны и расписание живут отдельно.',[
        'Что сдавать на этой неделе? Какие занятия займут мой день?',
        'Как распределить подготовку и не пропустить ближайшую работу?',
        'Ответ должен учитывать реальные записи LMS и права текущего студента.']),
      ('Один запрос вместо поиска','«Составь и сохрани план подготовки на неделю».',[
        'Агент получает предметы, дедлайны, расписание и личную нагрузку.',
        'Планировщик находит свободное время и отмечает нехватку времени.',
        'Студент проверяет предложение. Только после подтверждения появляются задачи.']),
      ('Архитектура','Один backend для локального и облачного агента.',[
        'Веб-интерфейс → Python API → Gemini на Vertex AI',
        'Gemini выбирает инструмент → настоящий MCP stdio-процесс',
        'MCP → серверные права и зачисления → Firebase Firestore',
        'Облачный вариант: API вызывает IAM-защищённый Agent Engine.']),
      ('Инструменты MCP','Каждый учебный факт приходит из инструмента.',[
        'get_courses / get_schedule / get_assignments: предметы, пары и дедлайны.',
        'get_grades / get_attendance: оценки и отмеченная посещаемость.',
        'read_materials: фрагменты материалов с указанием источника.',
        'plan_study / prepare_study_plan: расчёт и предложение записи.']),
      ('Reasoning loop','Модель выбирает следующий шаг по результатам инструментов.',[
        '1. Gemini получает запрос, контекст страницы и схемы инструментов.',
        '2. Function Call проверяется и выполняется через MCP.',
        '3. JSON-результат возвращается модели; цикл повторяется до ответа.',
        '4. UI показывает события, длительность, источники и ошибки.']),
      ('Связанные учебные данные','Расписание и работы больше не разрознены.',[
        '6 активных дисциплин, 10 недель, 120 занятий.',
        '60 заданий: Assignment 1–4, Midterm, Assignment 6–9, Endterm.',
        'Каждое задание связано с предметом, работой, занятием и дедлайном.',
        'Отсутствующая оценка не заменяется нулём. Оценка усилий редактируется.']),
      ('Облачное развёртывание','Подготовлен путь в Agent Engine и Cloud Run.',[
        'scripts/deploy_agent.py: dry-run и явный --execute.',
        'Современный SDK: vertexai.agent_engines.create.',
        'ADC / service account и Secret Manager; ключи не попадают в пакет.',
        'Gemini live и опубликованный endpoint требуют заполнения облачных слотов.']),
      ('Что показываем на защите','Проверяемое действие на каждом шаге.',[
        'Войти студентом. Открыть дедлайны и недельное расписание.',
        'Отправить запрос на план. Показать MCP-вызовы и результаты.',
        'Подтвердить задачи и открыть сохранённые записи.',
        'Режим Gemini: только после live-проверки модели и IAM.']),
      ('Проверка и границы','Не выдаём подготовку за выполненный деплой.',[
        'Firestore и реальный MCP проверяются отдельно от облачной модели.',
        'Автономные тесты: права, дедлайны, пересечения, подтверждения и MCP.',
        'Учётные данные MVP временные; Cloud Run демо остаётся приватным.',
        'Далее: live smoke-test Gemini, Agent Engine endpoint, демонстрация жюри.']),
      ('Настройки перед запуском','Слоты находятся в .env.example и cloud-config.example.env.',[
        'Ключ: CAMPUSPULSE_FIREBASE_CREDENTIALS = путь к приватному JSON.',
        'Vertex: GOOGLE_CLOUD_PROJECT / LOCATION / CAMPUSPULSE_VERTEX_MODEL.',
        'Облако: service account, staging bucket, ID секрета и resource name.',
        'Источники: cloud.google.com · googleapis.github.io/python-genai/']),
    ]
    for index,(title,subtitle,lines) in enumerate(slides,1):
        deck.setFillColor(HexColor('#00776B'));deck.setFont('ArialBold',12)
        deck.drawString(56,493,'CAMPUSPULSE AI   /   GDG ASTANA')
        deck.setFillColor(HexColor('#142E32'));deck.setFont('ArialBold',48 if index==1 else 32)
        deck.drawString(56,420,title)
        style=ParagraphStyle('subtitle',fontName='Arial',fontSize=22,leading=29,textColor=HexColor('#00776B'))
        p=Paragraph(subtitle,style);_,height=p.wrap(840,90);p.drawOn(deck,56,370-height+24)
        y=286
        body=ParagraphStyle('body',fontName='Arial',fontSize=18,leading=27,textColor=HexColor('#243C42'))
        for line in lines:
            p=Paragraph(line,body);_,height=p.wrap(830,120);p.drawOn(deck,56,y-height);y-=height+19
        if y<60:
            raise RuntimeError(f'Overflow on slide {index}')
        deck.setFont('Arial',10);deck.setFillColor(HexColor('#607B7D'))
        deck.drawString(56,28,'CampusPulse AI · Functional prototype · Deployment status is stated explicitly')
        deck.drawRightString(904,28,f'{index:02d} / {len(slides):02d}')
        deck.showPage()
    deck.save()
    print(OUT)


if __name__=='__main__':main()
