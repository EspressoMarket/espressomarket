exports.handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: 'Method not allowed' };
  }
  const { email } = JSON.parse(event.body);
  if (!email || !email.includes('@')) {
    return { statusCode: 400, body: 'Invalid email' };
  }
  const BEEHIIV_API_KEY = process.env.BEEHIIV_API_KEY;
  const BEEHIIV_PUBLICATION_ID = process.env.BEEHIIV_PUBLICATION_ID;
  const response = await fetch(`https://api.beehiiv.com/v2/publications/${BEEHIIV_PUBLICATION_ID}/subscriptions`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${BEEHIIV_API_KEY}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      email,
      reactivate_existing: true,
      send_welcome_email: true
    })
  });
  if (response.ok) {
    return { statusCode: 200, body: JSON.stringify({ success: true }) };
  } else {
    const err = await response.text();
    return { statusCode: 500, body: err };
  }
};
