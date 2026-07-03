from flask import Flask, jsonify

import GroupMeParser
import DashboardScript

app = Flask(__name__)


@app.route("/")
def dashboard():
    listings = DashboardScript.parse_bulk_file()
    return DashboardScript.render_html(listings)


@app.route("/update", methods=["POST"])
def update():
    added = GroupMeParser.sync()
    listings = DashboardScript.parse_bulk_file()
    return jsonify({"added": added, "listings": listings})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
