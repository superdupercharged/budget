FROM ubuntu 

RUN apt-get update
ENV TZ=Europe/Berlin \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install tzdata

RUN apt-get install -y ipython3 pip tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng

RUN pip install pandas termcolor pytesseract Pillow

CMD /bin/bash ; sleep infinity