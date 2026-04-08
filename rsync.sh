rsync -av /Users/filipuhlarik/coresearch -e "ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no" --exclude .lake_cache --exclude prepared_data chonker@192.168.101.15:/mnt/data
    