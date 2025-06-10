##########################
##  Create build image  ##
##########################
FROM python:3.13 as BUILD_IMAGE

# Set our working directory to /app
WORKDIR /app

# Copy only the requirements.txt files to utilize layer cache
COPY requirements.txt /app/

# Build python dependencies as wheels
RUN pip wheel -r requirements.txt --wheel-dir /wheels

##########################
## Create runtime image ##
##########################
FROM python:3.13-slim AS RUNTIME_IMAGE

# Install ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# Set our working directory to /app
WORKDIR /app

# Copy only the requirements.txt files to utilize layer cache
COPY requirements.txt /app/

# Copy our wakeup sound
COPY *.wav /app/

# Copy over wheels
COPY --from=BUILD_IMAGE /wheels /wheels

# Install wheels
RUN pip install -r requirements.txt --only-binary :all: --find-links /wheels

# Copy necessary source
COPY scripts/ /app/scripts/
COPY alembic.ini /app/
COPY migrations/ /app/migrations/
COPY roboToald/ /app/roboToald/
COPY batphone.py /app/

# Copy any CSV files for import
COPY *.csv /app/

# Run the app
CMD ["python", "-u", "./batphone.py"]
