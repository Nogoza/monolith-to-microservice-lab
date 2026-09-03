import http from "k6/http";
import { check, sleep } from "k6";

// Logs in, adds one item to the cart, then polls the cart every 2s for
// 3 minutes asserting the item is still there. This is a single
// continuous session and must run as a single VU / single iteration -
// splitting it up would hide exactly the failure mode it's checking for.
export const options = {
  vus: 1,
  iterations: 1,
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const USER_COUNT = parseInt(__ENV.USER_COUNT || "20000", 10);
const PASSWORD = "password123";
const POLL_INTERVAL_SECONDS = 2;
const TOTAL_DURATION_SECONDS = 180;

function csrfToken(url) {
  const jar = http.cookieJar();
  const cookies = jar.cookiesForURL(url);
  return cookies.csrftoken ? cookies.csrftoken[0] : null;
}

export default function () {
  const username = `user${Math.floor(Math.random() * USER_COUNT)}`;

  const loginPage = http.get(`${BASE_URL}/accounts/login/`);
  check(loginPage, { "login page 200": (r) => r.status === 200 });

  let token = csrfToken(`${BASE_URL}/accounts/login/`);
  const loginRes = http.post(
    `${BASE_URL}/accounts/login/`,
    { username: username, password: PASSWORD, csrfmiddlewaretoken: token },
    { headers: { "X-CSRFToken": token } }
  );
  check(loginRes, { "login succeeded": (r) => r.status === 200 || r.status === 302 });

  const list = http.get(`${BASE_URL}/products/`);
  const slugMatch = list.body.match(/\/products\/([a-z0-9-]+)\//);
  const productSlug = slugMatch ? slugMatch[1] : null;

  if (!productSlug) {
    throw new Error("Could not find a product to add to the cart.");
  }

  const detail = http.get(`${BASE_URL}/products/${productSlug}/`);
  const idMatch = detail.body.match(/cart\/add\/(\d+)\//);
  const productId = idMatch ? idMatch[1] : null;

  if (!productId) {
    throw new Error("Could not find a product id on the detail page.");
  }

  token = csrfToken(`${BASE_URL}/`);
  const addRes = http.post(
    `${BASE_URL}/cart/add/${productId}/`,
    { quantity: 1, csrfmiddlewaretoken: token },
    { headers: { "X-CSRFToken": token } }
  );
  check(addRes, { "add to cart succeeded": (r) => r.status === 200 || r.status === 302 });

  const iterations = Math.floor(TOTAL_DURATION_SECONDS / POLL_INTERVAL_SECONDS);

  for (let i = 0; i < iterations; i++) {
    sleep(POLL_INTERVAL_SECONDS);

    const cartRes = http.get(`${BASE_URL}/cart/`);
    const itemStillThere = cartRes.body.includes(`cart/remove/${productId}/`);

    check(cartRes, {
      "cart page 200": (r) => r.status === 200,
      "item still in cart": () => itemStillThere,
    });

    if (!itemStillThere) {
      console.error(`Item ${productId} missing from cart at poll ${i}`);
    }
  }
}
