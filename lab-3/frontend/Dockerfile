FROM nginx:1.28.0-alpine@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284
COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html app.js style.css /usr/share/nginx/html/
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
