from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.lib.units import mm


def make_pdf(assets, database, template='58x40', copies=1, skip=0):
    if template not in ('58x40','40x30','A4') or type(copies)!=int or not 1<=copies<=100 or type(skip)!=int or not 0<=skip<24:
        raise ValueError('Неверные параметры этикеток')
    w,h=(40,30) if template=='40x30' else (58,40)
    page=(210*mm,297*mm) if template=='A4' else (w*mm,h*mm)
    out=BytesIO(); pdf=canvas.Canvas(out,pagesize=page)
    slots=24 if template=='A4' else 1
    index=skip if template=='A4' else 0
    for asset in assets:
        # Core fonts lack Cyrillic; use a Unicode font when supplied by Windows/Linux.
        font='Helvetica'
        from pathlib import Path
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        for path in (Path('C:/Windows/Fonts/arial.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')):
            if path.exists():
                if 'LabelUnicode' not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont('LabelUnicode',str(path)))
                font='LabelUnicode'; break
        if font=='Helvetica' and any(ord(ch)>127 for ch in asset['number']):
            raise ValueError('Для кириллического номера нужен Arial или DejaVu Sans')
        for _ in range(copies):
            if index>=slots:
                pdf.showPage();index=0
            x=(10+(index%3)*63)*mm if template=='A4' else 0
            y=(297-10-(index//3+1)*34)*mm if template=='A4' else 0
            lw,lh=(58*mm,30*mm) if template=='A4' else (w*mm,h*mm)
            size=min(23*mm,lh-7*mm)
            qr=QrCodeWidget(f"INV1:{database}:{asset['id']}",barLevel='M',barBorder=4)
            bounds=qr.getBounds(); scale=size/(bounds[2]-bounds[0])
            drawing=Drawing(size,size,transform=[scale,0,0,scale,0,0]);drawing.add(qr)
            renderPDF.draw(drawing,pdf,x+2*mm,y+lh-size-2*mm)
            width=lw-size-6*mm
            text=asset['number']; lines=[]; current=''
            for ch in text:
                if pdfmetrics.stringWidth(current+ch,font,8)>width:
                    lines.append(current);current=''
                current+=ch
            if current: lines.append(current)
            if len(lines)*10>lh-4*mm: raise ValueError('Номер не помещается; выберите больший шаблон')
            pdf.setFont(font,8)
            for row,line in enumerate(lines): pdf.drawString(x+size+4*mm,y+lh-6*mm-row*10,line)
            index+=1
    pdf.save();return out.getvalue()
