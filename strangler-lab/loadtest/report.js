import http from "k6/http";
import { check } from "k6";

// Hammers the heavy synchronous sales report endpoint.
export const options = {
  vus: 3,
  duration: "1m",
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const USER_COUNT = parseInt(__ENV.USER_COUNT || "20000", 10);
const PASSWORD = "password123";

function csrfToken(url) {
  const jar = http.cookieJar();
  const cookies = jar.cookiesForURL(url);
  return cookies.csrftoken ? cookies.csrftoken[0] : null;
}

export default function () {
  const username = `user${Math.floor(Math.random() * USER_COUNT)}`;

  http.get(`${BASE_URL}/accounts/login/`);
  const token = csrfToken(`${BASE_URL}/accounts/login/`);

  http.post(
    `${BASE_URL}/accounts/login/`,
    { username: username, password: PASSWORD, csrfmiddlewaretoken: token },
    { headers: { "X-CSRFToken": token } }
  );

  const res = http.get(`${BASE_URL}/reports/sales/`);
  check(res, { "sales report 200": (r) => r.status === 200 });
}
