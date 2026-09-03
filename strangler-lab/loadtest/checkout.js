import http from "k6/http";
import { check, sleep } from "k6";

// Full flow: log in, browse, add an item to the cart, check out.
export const options = {
  vus: 5,
  duration: "1m",
  thresholds: {
    http_req_duration: ["p(95)<1000"],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
// Seeded users are user0..user19999, all sharing the seed password.
const USER_COUNT = parseInt(__ENV.USER_COUNT || "20000", 10);
const PASSWORD = "password123";

function csrfToken(url) {
  const jar = http.cookieJar();
  const cookies = jar.cookiesForURL(url);
  return cookies.csrftoken ? cookies.csrftoken[0] : null;
}

export default function () {
  const username = `user${Math.floor(Math.random() * USER_COUNT)}`;

  // 1. Load the login page to obtain a CSRF cookie.
  const loginPage = http.get(`${BASE_URL}/accounts/login/`);
  check(loginPage, { "login page 200": (r) => r.status === 200 });

  let token = csrfToken(`${BASE_URL}/accounts/login/`);

  // 2. Log in.
  const loginRes = http.post(
    `${BASE_URL}/accounts/login/`,
    { username: username, password: PASSWORD, csrfmiddlewaretoken: token },
    { headers: { "X-CSRFToken": token } }
  );
  check(loginRes, { "login succeeded": (r) => r.status === 200 || r.status === 302 });

  // 3. Browse the catalog and pick a product.
  const list = http.get(`${BASE_URL}/products/`);
  check(list, { "product list 200": (r) => r.status === 200 });

  const match = list.body.match(/\/products\/([a-z0-9-]+)\//);
  const productSlug = match ? match[1] : null;

  if (productSlug) {
    const detail = http.get(`${BASE_URL}/products/${productSlug}/`);
    check(detail, { "product detail 200": (r) => r.status === 200 });

    const productIdMatch = detail.body.match(/cart\/add\/(\d+)\//);
    const productId = productIdMatch ? productIdMatch[1] : null;

    if (productId) {
      token = csrfToken(`${BASE_URL}/`);

      // 4. Add to cart.
      const addRes = http.post(
        `${BASE_URL}/cart/add/${productId}/`,
        { quantity: 1, csrfmiddlewaretoken: token },
        { headers: { "X-CSRFToken": token } }
      );
      check(addRes, { "add to cart succeeded": (r) => r.status === 200 || r.status === 302 });

      // 5. Check out.
      const checkoutPage = http.get(`${BASE_URL}/orders/checkout/`);
      token = csrfToken(`${BASE_URL}/orders/checkout/`);

      const checkoutRes = http.post(
        `${BASE_URL}/orders/checkout/`,
        {
          shipping_address: "123 Load Test Street",
          payment_method: "card",
          csrfmiddlewaretoken: token,
        },
        { headers: { "X-CSRFToken": token } }
      );
      check(checkoutRes, { "checkout succeeded": (r) => r.status === 200 || r.status === 302 });
    }
  }

  sleep(1);
}
