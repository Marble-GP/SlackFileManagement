import os, ssl
import requests
import json
import re
from datetime import datetime
from slack_sdk.errors import SlackApiError
from slack_sdk.web import WebClient
from time import sleep

from my_smb import Smb


#******************************** Global variables ***************************************************** 

#true: when SSL verify error occurs, use unverified context    false: Exit with SSLCertVerificationError
USE_UNVERIFIED_CONTEXT = False

#Global::load config.json
try:
    with open("config.json", "r") as fp:
        conf = json.load(fp)
except FileNotFoundError as e:
    print("config.json not found. check the current directory.")
    exit(e.errno)


#******************************** my functions ***************************************************** 

def ssl_user_context(protocol=ssl.PROTOCOL_TLS, *, cert_reqs=ssl.CERT_REQUIRED,
                           check_hostname=True, purpose=ssl.Purpose.SERVER_AUTH,
                           certfile=None, keyfile=None,
                           cafile=conf["SSL_CAFILE"], capath=None, cadata=None):

    return ssl.create_default_context(purpose=purpose, cafile=cafile, capath=capath, cadata=cadata)


def json_timestamp_dump(dat:dict):
    with open(datetime.now().strftime("%Y%m%d-%H%M%S")+"_dump.json", "w") as fp:
        d = json.dumps(dat, sort_keys=True)
        fp.write(d)


def timestamp_print(text:str):
    print(datetime.now().isoformat(timespec="seconds")+" "+text)

#******************************** main code *********************************************************** 
if __name__ == "__main__":
    
    ssl._create_default_https_context = ssl_user_context

    #Create API connection
    client = WebClient(token=conf["API_TOKEN"])

    #API test
    try:
        api_res = client.api_test()
    except ssl.SSLCertVerificationError as ssl_err :
        print(ssl_err)

        if USE_UNVERIFIED_CONTEXT:
            timestamp_print("WARNING: Continue without SSL verification.")
            ssl._create_default_https_context = ssl._create_unverified_context
        else:
            exit(ssl_err.errno)
    
    if api_res["ok"]: #API test OK    
        
        #init slack information
        try:
            info = client.conversations_list(types="public_channel,private_channel,im")
            info.data = {"channels": []} #previous information has no data
        except SlackApiError as e:
            timestamp_print(str(e))
            timestamp_print("failed to get new conversations list for init.")

        timestamp_print("Slack API test is OK, File management app server started.")


        del client


        while True:

            #open new client
            client = WebClient(token=conf["API_TOKEN"])
            
            try:
                api_res = client.api_test()
            except ssl.SSLCertVerificationError as ssl_err :
                print(ssl_err)
                if USE_UNVERIFIED_CONTEXT:
                    timestamp_print("WARNING: Continue without SSL verification.")
                    ssl._create_default_https_context = ssl._create_unverified_context
                else:
                    exit(ssl_err.errno)
            
            if api_res["ok"]:
                #store old information
                pre_info = info.data.copy()

                #fetch new slack message information    
                try:
                    info = client.conversations_list(types="public_channel,private_channel,im")
                except SlackApiError as e:
                    timestamp_print(str(e))
                    timestamp_print("failed to get new conversations list.")

                
                if info["ok"]:
                    for d in info.data["channels"]:
                        if d not in pre_info["channels"]:#message update detection
                            try: 
                                #get new file list
                                #d["files"] = client.files_list(channel=d["id"]).data["files"]
                                d["messages"] = client.conversations_history(channel=d["id"]).data["messages"]

                            except SlackApiError as e:
                                timestamp_print(str(e))
                                if d["is_im"]:
                                    timestamp_print("failed to read im {}, id={}".format(d["user"], d["id"]))
                                else:
                                    timestamp_print("failed to read channel {}, id={}".format(d["name"], d["id"]))
                                continue

                            for message_info in d["messages"]:
                                if "files" not in message_info.keys():
                                    continue #pass the message
                                
                                #process each file sattached to a message
                                for file_info in message_info["files"]:
                                    #check file types and extentions
                                    arrow_save = file_info["filetype"] not in conf["SMB_FILETYPE_REJECT_LIST"] \
                                                and False not in [bool(re.fullmatch(os.path.splitext(file_info["name"])[1], ext, re.IGNORECASE) is None) for ext in conf["SMB_FILEEXT_REJECT_LIST"]]

                                    #download if has not been downloaded and appropriate file format
                                    if arrow_save:
                                        dat = requests.get(file_info["url_private_download"], headers={'Authorization': 'Bearer '+conf["API_TOKEN"]}).content
                                        
                                        try: # refer user name from user ID
                                            user_name = client.users_info(user=file_info["user"]).data["user"]["real_name"].replace(" ", "")    
                                        except SlackApiError as e:
                                            timestamp_print(str(e))
                                            timestamp_print("failed to get an information from user ID:"+str(file_info["user"]))
                                            continue

                                        #make target directory name and file name
                                        date_ts = datetime.fromtimestamp(file_info["timestamp"])
                                        target_dir_name1 = f"{date_ts.year}-{date_ts.month}"
                                        target_dir_name2 = user_name
                                        file_name = datetime.fromtimestamp(file_info["timestamp"]).strftime("%Y%m%d-%H%M%S") \
                                                    + f"_{user_name}_"+file_info["name"]
                        
                                        #make target path
                                        target_path1 = os.path.join(conf["SMB_STORE_PATH"], target_dir_name1)
                                        target_path2 = os.path.join(target_path1, target_dir_name2)
                                        target_file_path = os.path.join(target_path2, file_name)

                                        #open shared file server
                                        with Smb(conf["SMB_USER"], conf["SMB_PASS"], conf["SMB_REMOTE_NAME"], conf["SMB_HOST"]) as smb_conn:

                                            #Check if the file has already been downloaded
                                            if not smb_conn.exists(conf["SMB_SERVICE_NAME"], target_file_path):
                                                dat = requests.get(file_info["url_private_download"], headers={'Authorization': 'Bearer '+conf["API_TOKEN"]}).content
                                            else: #already exist
                                                # try:
                                                #     if conf["SLACK_APP_ID"] in client.reactions_get(channel=d["id"], file=file_info["id"], timestamp=file_info["timestamp"]).data["message"]["reactions"]:
                                                #         client.reactions_add(channel=d["id"], name="floppy_disk", timestamp=file_info["timestamp"])
                                                # except SlackApiError as e:
                                                #     timestamp_print(str(e))
                                                #     timestamp_print("Stamp response failed.")

                                                continue

                                            #make new month directory if not exist
                                            if not smb_conn.exists(conf["SMB_SERVICE_NAME"], target_path1):
                                                timestamp_print("make directry: "+target_path1)
                                                smb_conn.makedirs(conf["SMB_SERVICE_NAME"], target_path1)
                                            
                                            #make new user name directory if not exist
                                            if not smb_conn.exists(conf["SMB_SERVICE_NAME"], target_path2):
                                                timestamp_print("make directry: "+target_path2)
                                                smb_conn.makedirs(conf["SMB_SERVICE_NAME"], target_path2)

                                            if not smb_conn.exists(conf["SMB_SERVICE_NAME"], target_file_path):
                                                timestamp_print("save file: "+target_file_path)
                                                if smb_conn.save_file(dat, conf["SMB_SERVICE_NAME"], target_file_path):
                                                    try:
                                                        client.reactions_add(channel=d["id"], name="floppy_disk", timestamp=message_info["ts"])
                                                        
                                                    except SlackApiError as e:
                                                        timestamp_print(str(e))
                                                        timestamp_print("Stamp response failed.")
                                                else:
                                                    timestamp_print("Failed to save " +target_file_path) #error message
                
                else:# new client is not ok
                    sleep(60.0)

            #wait a few second for the next processing step
            del client
            sleep(2.0)

    else: #API test failure
        timestamp_print("Slack-SDK API test error")

