##########################
##  Create build image  ##
##########################
FROM python:3.9 as BUILD_IMAGE

# Set our working directory to /app
WORKDIR /app

# Copy only the requirements.txt files to utilize layer cache
COPY requirements.txt /app/

# Build python dependencies as wheels
RUN pip wheel -r requirements.txt --wheel-dir /wheels

##########################
## Create runtime image ##
##########################
FROM python:3.9-slim AS RUNTIME_IMAGE

# Set our working directory to /app
WORKDIR /app

# Copy only the requirements.txt files to utilize layer cache
COPY requirements.txt /app/

# Copy over wheels
COPY --from=BUILD_IMAGE /wheels /wheels

# Install wheels
RUN pip install -r requirements.txt --only-binary :all: --find-links /wheels

# Copy necessary source
COPY roboToald/ /app/roboToald/
COPY batphone.py /app/

# Run the app
CMD ["python", "-u", "./batphone.py"]
