#!/bin/sh
set -eu

case "${PLACEPULSE_REDIS_USER:-}" in
  ""|*[!A-Za-z0-9_-]*)
    echo "Invalid Redis ACL user" >&2
    exit 1
    ;;
esac

password_hash="$(sha256sum /run/secrets/redis_password | cut -d ' ' -f 1)"
umask 077
{
  echo "user default off"
  echo "user ${PLACEPULSE_REDIS_USER} on #${password_hash} ~placepulse:* &placepulse:* +@all -@admin -@dangerous"
} > /run/redis/users.acl
chown redis:redis /run/redis /run/redis/users.acl
chmod 0700 /run/redis
chmod 0600 /run/redis/users.acl

exec /usr/local/bin/docker-entrypoint.sh redis-server /usr/local/etc/redis/redis.conf
