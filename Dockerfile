# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Install dependencies
# Copy only requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Expose the port the app runs on
EXPOSE 5000

# Define the command to run the application
# Use gunicorn for a more robust server than Flask dev server (optional but good practice)
# RUN pip install --no-cache-dir gunicorn # Install gunicorn if using it
# CMD ["gunicorn", "--bind", "0.0.0.0:5000", "server.main:app"] # Example gunicorn command

# For simplicity with current setup (using Flask dev server):
CMD ["python", "server/main.py"] 