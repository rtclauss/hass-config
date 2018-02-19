FROM homeassistant/home-assistant:0.63.3
RUN apt update && apt install -y \ 
    git \
&& rm -rf /var/lib/apt/lists/*
RUN pip install git+https://github.com/jonatanolofsson/bellows.git
