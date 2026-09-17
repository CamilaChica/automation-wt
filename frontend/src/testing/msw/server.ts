import { setupServer } from 'msw/node';
import { thirdPartyHandlers } from './handlers';

export const thirdPartyMockServer = setupServer(...thirdPartyHandlers);
