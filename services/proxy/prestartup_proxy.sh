#!/bin/bash

#-----------------------
# JobFit Platform
#-----------------------

# Always create dir if not existent
mkdir -p /etc/letsencrypt/live/$JOBFIT_HOST/

# If there are no certificates, use snakeoils
if [ ! -f "/etc/letsencrypt/live/$JOBFIT_HOST/cert.pem" ]; then
    echo "Using default self-signed certificate cer file for $JOBFIT_HOST as not existent..."
    cp -a /root/certificates/selfsigned.crt /etc/letsencrypt/live/$JOBFIT_HOST/cert.pem
else
    echo "Not using default self-signed certificate cer file for $JOBFIT_HOST as already existent."
fi

if [ ! -f "/etc/letsencrypt/live/$JOBFIT_HOST/privkey.pem" ]; then
    echo "Using default self-signed certificate privkey file for $JOBFIT_HOST as not existent..."
    cp -a /root/certificates/selfsigned.key /etc/letsencrypt/live/$JOBFIT_HOST/privkey.pem
else
    echo "Not using default self-signed certificate privkey file for $JOBFIT_HOST as already existent."
fi

if [ ! -f "/etc/letsencrypt/live/$JOBFIT_HOST/fullchain.pem" ]; then
    echo "Using default self-signed certificate fullchain file for $JOBFIT_HOST as not existent..."
    cp -a /root/certificates/selfsigned.ca-bundle /etc/letsencrypt/live/$JOBFIT_HOST/fullchain.pem
else
    echo "Not using default self-signed certificate fullchain file for $JOBFIT_HOST as already existent."
fi

# Replace the JOBFIT_HOST in the Apache proxy conf. Directly using an env var doen not wotk
# with the letsencryot client, which has a bug: https://github.com/certbot/certbot/issues/8243
sudo sed -i "s/__JOBFIT_HOST__/$JOBFIT_HOST/g" /etc/apache2/sites-available/proxy-global.conf
    

#-----------------------
# JobFit tasks
#-----------------------

# If the tasks host is equal to jobfit host or not set, do nothing as we have already habdled it above
if [ "x$JOBFIT_TASKS_PROXY_HOST" == "x$JOBFIT_HOST" ] || [ "x$JOBFIT_TASKS_PROXY_HOST" == "x" ]; then
    echo "[INFO] Not setting up certificates forJobFit tasks host as qual to JobFit main host"
    JOBFIT_TASKS_PROXY_HOST=$JOBFIT_HOST
else

    # Always create dir if not existent
    mkdir -p /etc/letsencrypt/live/$JOBFIT_TASKS_PROXY_HOST/

    # If there are no certificates, use snakeoils
	if [ ! -f "/etc/letsencrypt/live/$JOBFIT_TASKS_PROXY_HOST/cert.pem" ]; then
	    echo "Using default self-signed certificate cer file for $JOBFIT_TASKS_PROXY_HOST as not existent..."
	    cp -a /root/certificates/selfsigned.crt /etc/letsencrypt/live/$JOBFIT_TASKS_PROXY_HOST/cert.pem
	else
	    echo "Not using default self-signed certificate cer file for $JOBFIT_TASKS_PROXY_HOST as already existent."
	fi
	
	if [ ! -f "/etc/letsencrypt/live/$JOBFIT_TASKS_PROXY_HOST/privkey.pem" ]; then
	    echo "Using default self-signed certificate privkey file for $JOBFIT_TASKS_PROXY_HOST as not existent..."
	    cp -a /root/certificates/selfsigned.key /etc/letsencrypt/live/$JOBFIT_TASKS_PROXY_HOST/privkey.pem
	else
	    echo "Not using default self-signed certificate privkey file for $JOBFIT_TASKS_PROXY_HOST as already existent."
	fi
	
	if [ ! -f "/etc/letsencrypt/live/$JOBFIT_TASKS_PROXY_HOST/fullchain.pem" ]; then
	    echo "Using default self-signed certificate fullchain file for $JOBFIT_TASKS_PROXY_HOST as not existent..."
	    cp -a /root/certificates/selfsigned.ca-bundle /etc/letsencrypt/live/$JOBFIT_TASKS_PROXY_HOST/fullchain.pem
	else
	    echo "Not using default self-signed certificate fullchain file for $JOBFIT_TASKS_PROXY_HOST as already existent."
	fi

fi

# Replace the __JOBFIT_TASKS_PROXY_HOST__ in the Apache proxy conf. Directly using an env var doen not wotk
# with the letsencryot client, which has a bug: https://github.com/certbot/certbot/issues/8243
sudo sed -i "s/__JOBFIT_TASKS_PROXY_HOST__/$JOBFIT_TASKS_PROXY_HOST/g" /etc/apache2/sites-available/proxy-global.conf
    
