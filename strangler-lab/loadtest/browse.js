import http from "k6/http";
import { check, sleep } from "k6";

// Baseline traffic: catalog browsing, no auth needed.
export const options = {
  vus: 20,
  duration: "2m",
  thresholds: {
    http_req_duration: ["p(95)<500"],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";

export default function () {
  const home = http.get(`${BASE_URL}/`);
  check(home, { "home 200": (r) => r.status === 200 });

  const list = http.get(`${BASE_URL}/products/`);
  check(list, { "product list 200": (r) => r.status === 200 });

  const page2 = http.get(`${BASE_URL}/products/?page=2`);
  check(page2, { "product list page 2 200": (r) => r.status === 200 });

  sleep(1);
}
