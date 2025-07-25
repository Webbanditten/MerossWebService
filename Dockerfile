FROM python:3.13-alpine
LABEL maintainer="patrick@webbanditten.dk"
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
EXPOSE 8080
ENTRYPOINT ["python"]
CMD ["src/app.py"]
