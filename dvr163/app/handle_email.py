import base64
import datetime
import dropbox
import email
import io
import json
import os
import re
import smtplib
import sys
from datetime import datetime
from requests import post
from shared import options, logger

###############################################################################
# Utility functions
###############################################################################


# Parse useful info from the text in the email body
def parse_text(msg):
    # Parse out the html text
    # TODO: Simplify with this? https://www.crummy.com/software/BeautifulSoup/bs4/doc/
    html_part = msg.get_payload(0).get_payload()
    # Remove style tags
    clean_html = re.sub(r"(?is)<(script|style).*?>.*?(</\1>)", "",
                        html_part.strip())
    # Get text content
    html_text = re.sub(r"(?s)<.*?>", " ", clean_html).strip()
    text_parts = html_text.split("; ")
    logger.debug("Found HTML text: " + html_text)
    message = text_parts[0][6:]
    channel_number = text_parts[0][-1:]
    date = text_parts[1][5:15]
    time = text_parts[1][16:]
    return {
        "html_text": html_text,
        "message": message,
        "channel_number": channel_number,
        "date": date,
        "time": time,
    }


###############################################################################
# Email actions
###############################################################################


# Send the info to Home Assistant
def to_home_assistant(msg):

    image_part = msg.get_payload(1).get_payload()
    parsed_text = parse_text(msg)
    channel_number = parsed_text["channel_number"]
    message = parsed_text["message"]

    # Notify Home Assistant
    logger.debug('Sending POST request')
    supervisor_token = os.environ['SUPERVISOR_TOKEN']
    base_url = os.getenv('HASS_API_BASE_URL', "http://supervisor/core/api/")
    data = {
        "channel_number": channel_number,
        "image_data": image_part,
        "message": message,
        "timestamp": datetime.now().strftime("%a %b %d, %I:%M:%S %p"),
    }
    headers = {
        "Authorization": "Bearer " + supervisor_token,
        "Content-Type": "application/json",
    }
    url = base_url + options["home_assistant"]["post_to"].lstrip("/")
    response = post(url, data=json.dumps(data), headers=headers)
    if (response.status_code >= 400):
        raise Exception("Bad response from Home Assistant: " + str(response))
    logger.info("Sent POST request to Home Assistant: " + url)


# Upload attached image to Dropbox
def to_dropbox(msg):

    # Initialize Dropbox client
    dbx = dropbox.Dropbox(options["dropbox"]["access_token"])

    # Read the image
    image_part = msg.get_payload(1).get_payload()
    file = io.BytesIO(base64.b64decode(image_part.encode("ascii"))).read()

    # Upload
    parsed_text = parse_text(msg)
    channel_number = parsed_text["channel_number"]
    date = parsed_text["date"]
    time = re.sub(r"[-:]", ".", parsed_text["time"])
    file_path = "/ch" + channel_number + "/" + date + "/" + time + ".jpg"
    logger.debug("Uploading " + file_path)
    file_data = dbx.files_upload(file, file_path, mute=True)

    logger.info("Uploaded " + file_path + " to Dropbox")


# Forward email somewhere else
def to_email(msg_data):
    username = options["email"]["username"]
    server = smtplib.SMTP(options["email"]["host"], options["email"]["port"])
    server.starttls()
    server.login(username, options["email"]["password"])
    # Ues the username as the from and to
    server.sendmail(username, username, msg_data)
    server.quit()
    logger.info("Email forwarded to " + username)


###############################################################################
# Main
###############################################################################


def main(email_data):

    # Parse email data into an email
    logger.debug("email_data:\n" + email_data)
    msg = email.message_from_string(email_data)

    # Do things with the email
    home_assistant_enabled = options["home_assistant"]["enabled"]
    dropbox_enabled = options["dropbox"]["enabled"]
    email_enabled = options["email"]["enabled"]

    if not (home_assistant_enabled) and not (dropbox_enabled) and not (
            email_enabled):
        logger.error("Message received but no destinations enabled!")
        sys.exit()

    if home_assistant_enabled:
        try:
            to_home_assistant(msg)
        except:
            logger.error("Error sending to Home Assistant: " +
                         str(sys.exc_info()))

    if dropbox_enabled:
        try:
            to_dropbox(msg)
        except:
            logger.error("Error uploading to dropbox: " + str(sys.exc_info()))

    if email_enabled:
        try:
            to_email(email_data)
        except:
            logger.error("Error forwarding email: " + str(sys.exc_info()))


# Support directly calling from command line with a file path containing the email_data
if __name__ == "__main__":
    f = open(sys.argv[1], "r")
    email_data = f.read()
    f.close()
    main(email_data)
