FROM ubuntu 

RUN apt-get update
ENV TZ=Europe/Berlin \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install tzdata

RUN apt-get install -y ipython3 pip

RUN pip install pandas termcolor

CMD /bin/bash ; sleep infinity