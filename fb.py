#!/usr/bin/env python3

import sys
import os
import argparse
import logging
import time
import requests
import json
import pickle
import email
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

config = {
    'url': 'https://www.facebook.com/api/graphql/',
    'c_user': '',
    'xs': '',
    'fb_dtsg': '',
    'user_agent': 'user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.109 Safari/537.36',
    'search_terms': ['hifi','audi a6'],
    'filter_location_id': '',
    'state_file': 'items.pickle',
    'email_server': '',
    'email_user': '',
    'email_from': '',
    'email_pass': '',
    'email_dest': ''
}
Session=None

def set_requests_session():
    s = requests.Session()
    retries=3
    a = requests.adapters.HTTPAdapter(max_retries=retries)
    b = requests.adapters.HTTPAdapter(max_retries=retries)
    s.mount('http://', a)
    s.mount('https://', b)
    return s

def do_get(url, stream=False, retries=3, retry_on=[500,501,502,503]):
    global Session
    if Session is None: Session = set_requests_session()
    res = None
    for r in range(retries):
        try:
            res = Session.get(url, stream=stream, timeout=30, verify=False, allow_redirects=False)
        except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
            logging.error("Could not connect to %s after %s attempts" % (url, retries))
            logging.debug(e)
            sys.exit(1)
        if res.status_code == 200:
            return res
        elif res.status_code in retry_on:
            print("%d/%d Retrying on %s http error..." % (r+1, retries, res.status_code))
            sleep(5)
    return res

def do_post(url, data, stream=False, retries=3, retry_on=[500,501,502,503]):
    global Session
    if Session is None: Session = set_requests_session()
    res = None
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    cookies = dict(c_user=config['c_user'],xs=config['xs'])
    for r in range(retries):
        try:
            res = Session.post(url, stream=stream, timeout=30, data=data, cookies=cookies, headers=headers)
        except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
            logging.error("Could not connect to %s after %s attempts" % (url, retries))
            logging.debug(e)
            sys.exit(1)
        if res.status_code == 200:
            return res
        elif res.status_code in retry_on:
            print("%d/%d Retrying on %s http error..." % (r+1, retries, res.status_code))
            sleep(5)
    return res

def search_fb_market(search_term,filter_location_id,known_items,new_items,fb_dtsg):
    logging.info("Searching for: "+search_term)
    search_term = search_term.replace(' ','%20')
    data = 'fb_dtsg='+fb_dtsg+'&variables=%7B%22MARKETPLACE_FEED_ITEM_IMAGE_WIDTH%22%3A246%2C%22VERTICALS_LEAD_GEN_PHOTO_HEIGHT_WIDTH%22%3A40%2C%22MERCHANT_LOGO_SCALE%22%3Anull%2C%22params%22%3A%7B%22bqf%22%3A%7B%22callsite%22%3A%22COMMERCE_MKTPLACE_WWW%22%2C%22query%22%3A%22'+search_term+'%22%7D%2C%22browse_request_params%22%3A%7B%22filter_location_id%22%3A%22'+filter_location_id+'%22%2C%22commerce_search_sort_by%22%3A%22CREATION_TIME_DESCEND%22%2C%22filter_price_lower_bound%22%3A0%2C%22filter_price_upper_bound%22%3A214748364700%7D%2C%22custom_request_params%22%3A%7B%22surface%22%3A%22SEARCH%22%2C%22search_vertical%22%3A%22C2C%22%7D%7D%7D&doc_id=1995581697207097'
    result = do_post(config['url'], data)
    try:
        result_json = json.loads(result.text)
    except:
        print(str(result.text))
        logging.exception("Failed to load json, check response text")
        sys.exit(1)
    for item in result_json['data']['marketplace_search']['feed_units']['edges']:
        if 'product_item' not in item['node']:
            continue
        logging.debug(json.dumps(item, sort_keys=True, indent=4, separators=(',', ': ')))
        id = item['node']['product_item']['for_sale_item']['id']
        item['creation_time'] = item['node']['product_item']['for_sale_item']['creation_time']
        item['creation_time_human'] = datetime.utcfromtimestamp(int(item['creation_time'])).strftime('%Y-%m-%d %H:%M:%S')
        item['item_title'] = item['node']['product_item']['for_sale_item']['group_commerce_item_title']
        item['price'] = item['node']['product_item']['for_sale_item']['formatted_price']['text']
        item['share_uri'] = item['node']['product_item']['for_sale_item']['share_uri']
        item['image'] = item['node']['product_item']['for_sale_item']['primary_listing_photo']['thumbnail']['uri']
        item['post_code'] = item['node']['product_item']['for_sale_item']['location']['reverse_geocode_detailed']['postal_code']
        if id not in known_items['items']:
            logging.info("Found new item: '"+item['item_title']+"' posted at: "+item['creation_time_human'])
            known_items['items'].append(id)
            new_items.append(item)
            save_known_items(known_items)
    return new_items

def notify(new_items):
    message = '<table>\n'
    for item in new_items:
        message += '<tr>'
        message += '<td>'+item['creation_time_human']+'</td>'
        message += '<td><a href="'+item['share_uri']+'">'+item['item_title']+' '+item['post_code']+'</a></td>'
        message += '<td>'+item['price']+'</td>'
        message += '<td><img style="margin: 0; border: 0; padding: 0; display: block;" height="100" src="'+item['image']+'"></img></td>'
        message += '</tr>\n\n'
    message += '</table>\n'
    send_mail('New items found for search: '+str(config['search_terms']), message, config['email_dest'])

def send_mail(subject,text_message,destination):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = config['email_from']
    msg['To'] = destination
    text_message = MIMEText(text_message, 'html')
    msg.attach(text_message)
    try:
        s = smtplib.SMTP(config['email_server'])
        s.login(config['email_user'], config['email_pass'])
        s.send_message(msg)
        s.quit()
        logging.info("Email sent successfully to: "+config['email_dest'])
    except:
        logging.error("Unknown error sending email: ", sys.exc_info()[0])

def load_known_items():
    try:
        with open(config['state_file']) as f:
            known_items = pickle.load(open(config['state_file'],'rb'))
    except IOError:
        logging.info("State file not found - Creating")
        known_items = {'items':[]}
        pickle.dump(known_items, open(config['state_file'],'wb'))
    except:
        logging.exception("Error loading state file")
        sys.exit(1)
    return known_items

def save_known_items(known_items):
    try:
        pickle.dump(known_items, open(config['state_file'],'wb'))
    except:
        logging.exception("Error saving state file")
        sys.exit(1)

# Main
def main():
    global args
    parser = argparse.ArgumentParser(description='Automate MS rewards')
    parser.add_argument('-l', '--log_level', default='info', help='log level')
    args = parser.parse_args()
    LogLevels = {'info': logging.INFO, 'error': logging.ERROR, 'debug': logging.DEBUG, 'critical': logging.CRITICAL}
    logging.basicConfig(
        level=LogLevels[args.log_level],
        format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
        datefmt='%d/%m/%Y %H:%M:%S')

    known_items = load_known_items()
    new_items = []
    for search_term in config['search_terms']:
        new_items += search_fb_market(search_term, config['filter_location_id'], known_items, new_items, config['fb_dtsg'])
    if len(new_items) > 0:
        notify(new_items)
    else:
        logging.info("No new items found")

if __name__ == '__main__':
    main()

# vim: ts=4 expandtab background=dark ft=python
