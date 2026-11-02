from app import create_app

app = create_app()

if __name__ == "__main__":
    print(f"Open http://{app.config['HOST']}:{app.config['PORT']}")
    # threaded=True keeps live event streams from blocking other requests.
    app.run(host=app.config["HOST"], port=app.config["PORT"], threaded=True, debug=False)
