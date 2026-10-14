#!/usr/bin/env python3
import http.client
import ssl
import sys


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "nginx"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 443
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    path = sys.argv[4] if len(sys.argv) > 4 else "/api/tasks"

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    connection = http.client.HTTPSConnection(host, port, context=context, timeout=5)
    codes = []
    try:
        for _ in range(count):
            try:
                connection.request("GET", path, headers={"Host": "lab1.local"})
                response = connection.getresponse()
                response.read()
                codes.append(str(response.status))
            except (OSError, http.client.HTTPException):
                connection.close()
                connection = http.client.HTTPSConnection(
                    host, port, context=context, timeout=5
                )
                codes.append("000")
    finally:
        connection.close()

    print(" ".join(codes))


if __name__ == "__main__":
    main()

