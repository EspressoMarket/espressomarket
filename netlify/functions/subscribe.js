exports.handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method Not Allowed" };
  }

  const { email, niva } = JSON.parse(event.body);
  if (!email) return { statusCode: 400, body: "Email saknas" };

  const BEEHIIV_KEY = process.env.BEEHIIV_API_KEY;
  const BEEHIIV_PUB = process.env.BEEHIIV_PUBLICATION_ID;

  const response = await fetch(
    `https://api.beehiiv.com/v2/publications/${BEEHIIV_PUB}/subscriptions`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${BEEHIIV_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        email,
        reactivate_existing: true,
        send_welcome_email: true,
        custom_fields: [
          { name: "niva", value: niva || "beginner" }
        ],
      }),
    }
  );

  if (response.ok) {
    return { statusCode: 200, body: "OK" };
  } else {
    const err = await response.text();
    console.error("Beehiiv fel:", err);
    return { statusCode: 500, body: "Fel" };
  }
};
