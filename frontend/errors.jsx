import React, { Component } from 'react';
import { Button, Card, CardBody } from '@utkristi/ui';

export function ErrorPage({ notFound = false, retry, title, description }) {
  return <Card className="panel error-page">
    <CardBody className="stack">
      {notFound && <div className="eyebrow">404</div>}
      <h1>{title ?? (notFound ? 'Page not found' : 'Something went wrong')}</h1>
      <p>{description ?? (notFound
        ? 'Check the address or return to the workspace.'
        : 'ClearRemit couldn’t load this page. Try again or return to the workspace.')}</p>
      <div className="actions">
        {retry && <Button onClick={retry}>Try again</Button>}
        <Button href="/app" variant={retry ? 'ghost' : 'solid'}>Back to workspace</Button>
      </div>
    </CardBody>
  </Card>;
}

export class ErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return <ErrorPage retry={() => location.reload()} />;
    }
    return this.props.children;
  }
}
